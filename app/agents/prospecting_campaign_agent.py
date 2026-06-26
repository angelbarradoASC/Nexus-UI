"""
app/agents/prospecting_campaign_agent.py
------------------------------------------
Agente diario de prospección para campañas outreach automatizadas.

Flujo completo:
  1. Corre follow-ups vencidos de campañas activas (≤ 2 por prospecto)
  2. Busca nuevas empresas en web via Brave → valida emails → deduplica vs CRM
  3. Toma los 20 primeros nuevos → lanza campaña outreach (email inicial)
  4. Sincroniza al CRM

No bloquea el arranque: si el SMTP no está configurado, registra el error
y continúa sin crashear el servidor.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


class ProspectingCampaignAgent:
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
            "vertical": "inmobiliaria",
            "target_description": "agencias inmobiliarias, portales y gestoras de propiedades",
            "desired_count": 30,
            "daily_send_cap": 20,
            "followup_delays_days": [14, 14],
            "proposition": (
                "ayudamos a empresas del sector inmobiliario a tener visibilidad total "
                "de su infraestructura IT: servidores, sistemas de gestión, portales y "
                "conectividad — sin necesidad de un equipo técnico propio"
            ),
            "cta": (
                "¿Te encajaría una llamada de 15 minutos esta semana para ver si tiene "
                "sentido para vuestro equipo?"
            ),
            "audience_hint": "agencias inmobiliarias, portales de propiedades, gestoras",
            "sender_name": "",
            "geography": "",
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
        Seguro de llamar aunque falle SMTP o Brave.
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
        vertical     = cfg.get("vertical", "inmobiliaria")
        target_desc  = cfg.get("target_description", "")
        desired      = int(cfg.get("desired_count", 30))
        daily_cap    = int(cfg.get("daily_send_cap", 20))
        followups    = cfg.get("followup_delays_days", [14, 14])
        proposition  = cfg.get("proposition", "")
        cta          = cfg.get("cta", "")
        audience     = cfg.get("audience_hint", "")
        geography    = cfg.get("geography", "")

        logger.info(
            "Prospección nueva | vertical={} | deseados={} | cap={}",
            vertical, desired, daily_cap,
        )

        # 1. Buscar prospectos (run() solo retorna resumen; los resultados se leen aparte)
        pros_summary = await self._prospecting.run({
            "vertical":            vertical,
            "target_description":  target_desc,
            "city":                geography,
            "desired_count":       desired,
            "minimum_score":       40,
            "dry_run":             False,
            "async_mode":          False,
        })

        run_id = pros_summary.get("run_id")
        # Obtener resultados reales filtrados por crm_state == "pending" (no duplicados)
        results_payload = await self._prospecting.list_results(
            run_id=run_id, crm_state="pending"
        )
        all_results = results_payload.get("results", [])
        new_prospects = [r for r in all_results if r.get("email")][:daily_cap]

        logger.info(
            "Prospección | run_id={} | usables={} | a_contactar={}",
            run_id, len(all_results), len(new_prospects),
        )

        if not new_prospects:
            return {"status": "no_new_prospects", "sent_count": 0}

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

        # 3. Sync al CRM
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
        }

    # ── Helper ────────────────────────────────────────────────────────────────

    @staticmethod
    def _map_prospect(p: dict[str, Any]) -> dict[str, Any]:
        """Normaliza un resultado de ProspectingAgentService al formato de OutreachManager."""
        contact = p.get("contact_person") or ""
        first = contact.split()[0] if contact else ""
        notes_raw = p.get("notes") or []
        notes_str = " | ".join(str(n) for n in notes_raw) if isinstance(notes_raw, list) else str(notes_raw)
        return {
            "email":          p.get("email", ""),
            "first_name":     first,
            "company":        p.get("name") or "",
            "job_title":      p.get("contact_role") or "",
            "company_domain": p.get("domain") or "",
            "notes":          notes_str,
        }
