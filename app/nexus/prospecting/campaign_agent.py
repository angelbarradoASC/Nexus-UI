"""
app/nexus/prospecting/campaign_agent.py
------------------------------------------
Agente diario de prospección para campañas outreach automatizadas.

Flujo completo:
  1. Corre follow-ups vencidos de campañas activas
  2. Busca nuevas empresas (discovery + auditoria tecnica + perfil + propuesta
     + score de oportunidad, vía ProspectingAgentService.run(enrich_candidates=True))
  3. Toma los QUALIFIED (superan opportunity_threshold), hasta daily_send_cap
     — deliberadamente bajo (por defecto 2): pocos contactos, muy cuidados
  4. Lanza campaña outreach con el hallazgo real de cada lead
  5. Marca CONTACTED en el lead de origen y sincroniza al CRM

No bloquea el arranque: si el SMTP no está configurado, registra el error
y continúa sin crashear el servidor. Reubicado desde
app/agents/prospecting_campaign_agent.py (recuperado tras su borrado en
d6a3d79) junto a lo que orquesta — adaptado a la firma actual de
ProspectingAgentService.run(), que ahora espera un ProspectingRunRequest,
no un dict, y expone enrich_candidates/opportunity_threshold/lead_stage.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from nexus.api.schemas.prospecting import ProspectingRunRequest


class CampaignAgent:
    """
    Orquesta ProspectingAgentService + OutreachManager + CRMBridgeService
    para ejecutar la campaña diaria de forma autónoma.

    Se instancia una vez y se llama con run_daily() desde el scheduler.
    """

    def __init__(
        self,
        *,
        prospecting_svc,
        outreach_mgr,
        crm_svc,
        config_path: str | Path = "data/campaigns/daily_config.json",
    ) -> None:
        self._prospecting = prospecting_svc
        self._outreach    = outreach_mgr
        self._crm         = crm_svc
        self._config_path = Path(config_path)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._config_path.exists():
            self._write_default_config()

    # ── Config ────────────────────────────────────────────────────────────────

    def _write_default_config(self) -> None:
        default = {
            "enabled": True,
            "vertical": "custom",
            "target_description": "",
            "geography": "",
            "desired_count": 30,
            # Deliberadamente bajo — "2 contactos excelentes al día, no 200
            # mediocres" (restriccion explicita del usuario, no un default
            # arbitrario).
            "daily_send_cap": 2,
            "minimum_score": 40,
            "opportunity_threshold": 55,
            "followup_delays_days": [14, 14],
            "proposition": "",
            "cta": (
                "¿Te encajaría una llamada de 15 minutos esta semana para ver si tiene "
                "sentido para vuestro equipo?"
            ),
            "audience_hint": "",
            "sender_name": "",
            "represented_by": "assets",
            "notes": "Edita este fichero para personalizar la campaña. enabled=false la pausa.",
        }
        self._config_path.write_text(
            json.dumps(default, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Config de campaña creada en {}", self._config_path)

    def load_config(self) -> dict[str, Any]:
        try:
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_config(self, config: dict[str, Any]) -> None:
        self._config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run_daily(self) -> dict[str, Any]:
        """
        Ejecuta el ciclo completo del día.
        Seguro de llamar aunque falle SMTP, Obscura o el LLM.
        """
        cfg = self.load_config()
        if not cfg.get("enabled", True):
            logger.info("Campaña diaria deshabilitada (enabled=false)")
            return {"status": "disabled"}

        started = datetime.now(timezone.utc).isoformat()
        report: dict[str, Any] = {
            "status":      "ok",
            "started_at":  started,
            "followups":   {},
            "new_campaign": {},
            "errors":      [],
        }

        # ── 1. Follow-ups vencidos ────────────────────────────────────────────
        try:
            followup_result = await self._run_followups()
            report["followups"] = followup_result
        except Exception as exc:
            logger.error("Error en follow-ups: {}", exc)
            report["errors"].append(f"followups: {exc}")

        # ── 2. Nuevos prospectos ──────────────────────────────────────────────
        try:
            new_result = await self._run_new_prospects(cfg)
            report["new_campaign"] = new_result
        except Exception as exc:
            logger.error("Error en prospección nueva: {}", exc)
            report["errors"].append(f"new_prospects: {exc}")

        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Campaña diaria completada | followups={} | nuevos_enviados={} | errores={}",
            report["followups"].get("executed_count", 0),
            report["new_campaign"].get("sent_count", 0),
            len(report["errors"]),
        )
        return report

    # ── Follow-ups ────────────────────────────────────────────────────────────

    async def _run_followups(self) -> dict[str, Any]:
        campaigns = await self._outreach._repository.load_campaigns()
        active = [
            c for c in campaigns
            if any(
                p.get("status") == "waiting_followup"
                for p in c.get("prospects", [])
            )
        ]
        if not active:
            logger.info("Sin follow-ups vencidos hoy")
            return {"executed_count": 0, "campaigns_checked": 0}

        total_sent = 0
        for campaign in active:
            result = await self._outreach.run_campaign(
                campaign["campaign_id"], dry_run=False
            )
            sent = result.get("executed_count", 0)
            total_sent += sent
            if sent:
                logger.info(
                    "Follow-up | campaña={} | enviados={}",
                    campaign.get("campaign_name", campaign["campaign_id"]),
                    sent,
                )

        return {"executed_count": total_sent, "campaigns_checked": len(active)}

    # ── Nuevos prospectos ─────────────────────────────────────────────────────

    async def _run_new_prospects(self, cfg: dict[str, Any]) -> dict[str, Any]:
        vertical     = cfg.get("vertical", "custom")
        target_desc  = cfg.get("target_description", "")
        desired      = int(cfg.get("desired_count", 30))
        daily_cap    = int(cfg.get("daily_send_cap", 2))
        minimum_score = int(cfg.get("minimum_score", 40))
        opportunity_threshold = int(cfg.get("opportunity_threshold", 55))
        followups    = cfg.get("followup_delays_days", [14, 14])
        proposition  = cfg.get("proposition", "")
        cta          = cfg.get("cta", "")
        audience     = cfg.get("audience_hint", "")
        geography    = cfg.get("geography", "")
        represented_by = cfg.get("represented_by", "assets")

        logger.info(
            "Prospección nueva | vertical={} | deseados={} | cap={} | umbral_oportunidad={}",
            vertical, desired, daily_cap, opportunity_threshold,
        )

        # 1. Buscar + auditar + perfilar + proponer + puntuar oportunidad — todo
        # dentro de ProspectingAgentService.run() vía enrich_candidates=True.
        request = ProspectingRunRequest(
            vertical=vertical,
            target_description=target_desc,
            city=geography,
            desired_count=desired,
            minimum_score=minimum_score,
            opportunity_threshold=opportunity_threshold,
            represented_by=represented_by,
            dry_run=False,
            async_mode=False,
            enrich_candidates=True,
        )
        pros_summary = await self._prospecting.run(request)

        run_id = pros_summary.get("run_id")
        # Solo los que ya superaron el umbral de oportunidad (QUALIFIED) y no
        # estan ya en CRM (crm_state=pending) — el filtro por lead_stage es lo
        # que hace que "2 contactos excelentes" sea real y no solo un limite
        # numerico sobre resultados mediocres.
        results_payload = await self._prospecting.list_results(
            run_id=run_id, crm_state="pending", lead_stage="QUALIFIED"
        )
        all_results = results_payload.get("results", [])
        new_prospects = [r for r in all_results if r.get("email")][:daily_cap]

        logger.info(
            "Prospección | run_id={} | qualified={} | a_contactar={}",
            run_id, len(all_results), len(new_prospects),
        )

        if not new_prospects:
            return {"status": "no_qualified_prospects", "sent_count": 0, "run_id": run_id}

        # 2. Lanzar campaña outreach
        campaign_name = f"{vertical.capitalize()} {date.today().isoformat()}"
        campaign_result = await self._outreach.launch_campaign({
            "campaign_name":         campaign_name,
            "proposition":           proposition,
            "cta":                   cta,
            "audience_hint":         audience,
            "followup_delays_days":  followups,
            "max_daily_send":        daily_cap,
            "dry_run":               False,
            "prospects":             [self._map_prospect(p) for p in new_prospects],
        })

        campaign_id = campaign_result.get("campaign_id")
        sent_count  = campaign_result.get("executed_count", 0)

        logger.info(
            "Campaña lanzada | id={} | enviados={}",
            campaign_id, sent_count,
        )

        # 3. Marcar CONTACTED en el lead de origen — simplificacion: se marca
        # cada prospecto enviado en este lote (daily_cap ya limitaba de
        # antemano cuantos entraban, asi que todos los que entran se procesan
        # en la misma tanda). El estado de entrega real (enviado/fallido)
        # sigue disponible en el evento de outreach, esto solo mueve la etapa
        # comercial del lead.
        for prospect in new_prospects:
            result_id = prospect.get("result_id")
            if result_id:
                try:
                    await self._prospecting.mark_lead_stage(result_id, "CONTACTED")
                except Exception as exc:
                    logger.warning("mark_lead_stage fallido (no critico) | {} | {}", result_id, exc)

        # 4. Sync al CRM
        if campaign_id:
            try:
                await self._crm.sync_campaign(
                    campaign_id, limit=daily_cap, dry_run=False
                )
                logger.info("CRM sync OK | campaña={}", campaign_id)
            except Exception as exc:
                logger.warning("CRM sync fallido (no crítico): {}", exc)

        return {
            "status":      "launched",
            "campaign_id": campaign_id,
            "sent_count":  sent_count,
            "prospects":   len(new_prospects),
            "vertical":    vertical,
            "run_id":      run_id,
        }

    # ── Helper ────────────────────────────────────────────────────────────────

    @staticmethod
    def _map_prospect(p: dict[str, Any]) -> dict[str, Any]:
        """Normaliza un result de ProspectingAgentService al formato de
        OutreachManager, incluyendo el hallazgo real (business_profile/
        proposal_items) que _draft_message usa para personalizar el mensaje."""
        contact = p.get("contact_person") or ""
        first = contact.split()[0] if contact else ""
        notes_raw = p.get("notes") or []
        notes_str = " | ".join(str(n) for n in notes_raw) if isinstance(notes_raw, list) else str(notes_raw)
        return {
            "email":            p.get("email", ""),
            "first_name":       first,
            "company":          p.get("name") or "",
            "job_title":        p.get("contact_role") or "",
            "company_domain":   p.get("domain") or "",
            "notes":            notes_str,
            "run_id":           p.get("run_id", ""),
            "result_id":        p.get("result_id", ""),
            "business_profile": p.get("business_profile") or {},
            "proposal_items":   (p.get("proposal") or {}).get("items", []),
        }
