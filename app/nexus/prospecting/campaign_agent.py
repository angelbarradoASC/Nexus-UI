"""
app/nexus/prospecting/campaign_agent.py
------------------------------------------
Agente diario de prospección para campañas outreach automatizadas.

Flujo completo (run_daily, disparado por el scheduler o /campaign/trigger):
  1. Corre follow-ups vencidos de campañas activas
  2. Busca nuevas empresas (discovery + auditoria tecnica + perfil + propuesta
     + score de oportunidad, vía ProspectingAgentService.run(enrich_candidates=True))
  3. Alimenta el CRM con TODO lo descubierto (push_valid_to_crm), no solo lo
     que se acabe contactando
  4. Con require_manual_approval=true (default — restriccion explicita del
     usuario: "yo decido a quien escribo"), el ciclo PARA AQUI: los QUALIFIED
     (superaron opportunity_threshold) quedan en cola de revision
     (list_pending_review) sin enviar nada. Solo send_to_prospect(), llamado
     desde /campaign/pending/{id}/send cuando el usuario aprueba un lead
     concreto, lanza el outreach, marca CONTACTED y sincroniza ese lead al CRM.
     Con require_manual_approval=false se mantiene el modo 100% autonomo de
     antes: toma los QUALIFIED hasta daily_send_cap — deliberadamente bajo
     (por defecto 2) — y los envia/marca/sincroniza en la misma pasada.

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
            # Por defecto NADIE se contacta solo — el ciclo diario descubre,
            # audita, puntua y deja los QUALIFIED en cola de revision
            # (restriccion explicita del usuario: "yo decido a quien escribo").
            # Poner esto a false vuelve al envio 100% autonomo de antes.
            "require_manual_approval": True,
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
        require_manual_approval = bool(cfg.get("require_manual_approval", True))

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

        # Alimentar el CRM con TODO lo descubierto (no solo lo que se decida
        # contactar) — push_valid_to_crm ya filtra por crm_ready (datos
        # limpios/sin duplicar), no por lead_stage, asi que cubre tambien los
        # REJECTED. Restriccion explicita del usuario: el CRM debe reflejar
        # todo lo encontrado, no solo lo contactado. No critico: un fallo aqui
        # no debe tumbar el resto del ciclo.
        try:
            crm_feed = await self._prospecting.push_valid_to_crm(run_id, dry_run=False)
            logger.info(
                "CRM alimentado con todo lo descubierto | run_id={} | pushed={}",
                run_id, crm_feed.get("pushed_count", 0),
            )
        except Exception as exc:
            logger.warning("Fallo alimentando el CRM con el run completo (no critico): {}", exc)

        # Solo los que ya superaron el umbral de oportunidad (QUALIFIED) — el
        # filtro por lead_stage es lo que hace que "2 contactos excelentes"
        # sea real y no solo un limite numerico sobre resultados mediocres.
        # NO se filtra por crm_state="pending": push_valid_to_crm (arriba)
        # acaba de dejar estos mismos resultados en crm_state="created", asi
        # que ese filtro nunca encontraria nada — mismo bug ya corregido en
        # list_pending_review, misma causa (crm_state trackea sincronizacion
        # con el CRM, no si un humano ya decidio que hacer con el lead).
        results_payload = await self._prospecting.list_results(
            run_id=run_id, lead_stage="QUALIFIED"
        )
        all_results = results_payload.get("results", [])
        new_prospects = [r for r in all_results if r.get("email")][:daily_cap]

        logger.info(
            "Prospección | run_id={} | qualified={} | a_contactar={}",
            run_id, len(all_results), len(new_prospects),
        )

        if not new_prospects:
            return {"status": "no_qualified_prospects", "sent_count": 0, "run_id": run_id}

        if require_manual_approval:
            # No se envia nada solo — se deja en cola de revision
            # (GET /campaign/pending) para que el usuario decida a quien
            # escribir. Nunca se llama a launch_campaign ni se marca
            # CONTACTED aqui; eso solo ocurre via send_to_prospect().
            logger.info(
                "Prospeccion en cola de revision (require_manual_approval=true) | run_id={} | pendientes={}",
                run_id, len(new_prospects),
            )
            return {
                "status":            "pending_review",
                "sent_count":        0,
                "pending_review_count": len(new_prospects),
                "run_id":            run_id,
                "vertical":          vertical,
            }

        # 2. Lanzar campaña outreach
        campaign_name = f"{vertical.capitalize()} {date.today().isoformat()}"
        try:
            campaign_result = await self._outreach.launch_campaign({
                "campaign_name":         campaign_name,
                "sender_name":           cfg.get("sender_name", ""),
                "proposition":           proposition,
                "cta":                   cta,
                "audience_hint":         audience,
                "followup_delays_days":  followups,
                "max_daily_send":        daily_cap,
                "dry_run":               False,
                "prospects":             [self._map_prospect(p) for p in new_prospects],
            })
        except Exception as exc:
            # launch_campaign exige sender_name (propio o cfg.outreach_
            # sender_name) — sin este catch, un ciclo diario entero se
            # marcaria como error en vez de devolver un status legible.
            logger.error("Fallo lanzando la campaña outreach: {}", exc)
            return {"status": "error", "error": str(exc), "sent_count": 0, "run_id": run_id}

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

    # ── Cola de revision humana ──────────────────────────────────────────────
    # Con require_manual_approval=true (default), run_daily() ya no envia
    # nada solo — deja los QUALIFIED aqui hasta que el usuario elija por cada
    # uno. Estos 3 metodos son el unico camino para pasar de "descubierto" a
    # "contactado" en ese modo.

    async def list_pending_review(self) -> list[dict[str, Any]]:
        """Leads QUALIFIED de cualquier run reciente que aun no se han
        contactado ni descartado — la cola que el usuario revisa antes de
        decidir a quien escribir.

        lead_stage="QUALIFIED" esta sobrecargado: en una busqueda normal de
        Sales (enrich_candidates=False) tambien se pone QUALIFIED a cualquier
        resultado que pase el filtro basico de calidad/dedupe — sin auditoria,
        sin propuesta, sin opportunity_score. Aqui solo interesan los que de
        verdad pasaron por el scoring de oportunidad de una campaña
        (_enrich_accepted_candidate) — se distinguen porque ese es el unico
        camino que rellena opportunity_score.

        No se filtra por crm_state: ese campo trackea si ya se sincronizo al
        CRM (pending/created/duplicate), algo ortogonal a si un humano ya
        decidio que hacer con el lead — y como _run_new_prospects ahora
        alimenta el CRM con TODO lo descubierto en cuanto se encuentra, un
        lead recien calificado ya tiene crm_state="created" de inmediato,
        nunca "pending". Lo que de verdad saca un lead de esta cola es que su
        lead_stage deje de ser QUALIFIED (send_to_prospect -> CONTACTED,
        discard_prospect -> DISCARDED)."""
        payload = await self._prospecting.list_results(lead_stage="QUALIFIED")
        return [
            r for r in payload.get("results", [])
            if r.get("email") and r.get("opportunity_score") is not None
        ]

    async def list_pending(self) -> list[dict[str, Any]]:
        """Adaptador para NexusCoordinator.list_pending_actions() — misma
        forma {context_id, agent_id, kind, summary} que usan Mouse/SystemTask/
        RemoteOps/SelfConfig, para que la cola de Campaña aparezca junto al
        resto en la pestaña Agentes sin duplicar la logica de
        list_pending_review(). context_id lleva el prefijo "campaign:" para
        que el coordinador pueda enrutar confirm/cancel a send_to_prospect/
        discard_prospect en vez del bucle has_pending() (Campaña no lo
        implementa — su "pendiente" es una cola de leads, no un unico estado
        por conversacion)."""
        pending = await self.list_pending_review()
        return [
            {
                "context_id": f"campaign:{r['result_id']}",
                "agent_id": "campaign",
                "kind": "review",
                "summary": f"{r.get('name', 'lead')} — oportunidad {r.get('opportunity_score')}",
            }
            for r in pending
        ]

    async def send_to_prospect(self, result_id: str) -> dict[str, Any]:
        """Envia el outreach a UN lead concreto de la cola de revision, elegido
        por el usuario. Reusa la propuesta/CTA/follow-ups de la config vigente
        — mismo tono que tendria el envio automatico, solo que decidido por
        persona, no por umbral."""
        pending = await self.list_pending_review()
        prospect = next((r for r in pending if r.get("result_id") == result_id), None)
        if prospect is None:
            return {"status": "not_found", "result_id": result_id}

        cfg = self.load_config()
        campaign_name = f"{prospect.get('name', 'lead')} {date.today().isoformat()}"
        try:
            campaign_result = await self._outreach.launch_campaign({
                "campaign_name":        campaign_name,
                "sender_name":          cfg.get("sender_name", ""),
                "proposition":          cfg.get("proposition", ""),
                "cta":                  cfg.get("cta", ""),
                "audience_hint":        cfg.get("audience_hint", ""),
                "followup_delays_days": cfg.get("followup_delays_days", [14, 14]),
                "max_daily_send":       1,
                "dry_run":              False,
                "prospects":            [self._map_prospect(prospect)],
            })
        except Exception as exc:
            # launch_campaign exige sender_name (propio o de cfg.outreach_
            # sender_name) y puede fallar tambien si el SMTP no esta
            # configurado — sin este catch, el usuario veria un 500 sin
            # explicacion al pulsar "Enviar" en vez de un error legible.
            logger.warning("send_to_prospect fallo al lanzar la campaña | {} | {}", result_id, exc)
            return {"status": "failed", "result_id": result_id, "error": str(exc)}

        campaign_id = campaign_result.get("campaign_id")
        sent_count  = campaign_result.get("executed_count", 0)
        # executed_count solo dice "se proceso un intento de envio", no que
        # el email de verdad saliera — SMTPOutreachTransport.send() no lanza
        # si el SMTP no esta configurado, devuelve delivery_status=
        # "not_configured" y run_campaign lo cuenta igual como "ejecutado".
        # Sin mirar el evento real, se reportaria "enviado" sin haber
        # enviado nada.
        events = campaign_result.get("events") or []
        delivery_status = events[0].get("delivery_status") if events else None
        delivered = delivery_status == "sent"

        if delivered:
            try:
                await self._prospecting.mark_lead_stage(result_id, "CONTACTED")
            except Exception as exc:
                logger.warning("mark_lead_stage fallido (no critico) | {} | {}", result_id, exc)

            if campaign_id:
                try:
                    await self._crm.sync_campaign(campaign_id, limit=1, dry_run=False)
                except Exception as exc:
                    logger.warning("CRM sync fallido (no critico): {}", exc)

        logger.info(
            "Envio manual aprobado | lead={} | campaign_id={} | delivery_status={}",
            prospect.get("name"), campaign_id, delivery_status,
        )
        if delivered:
            return {"status": "sent", "result_id": result_id, "campaign_id": campaign_id, "sent_count": sent_count}
        error = "SMTP no configurado" if delivery_status == "not_configured" else f"delivery_status={delivery_status}"
        return {"status": "failed", "result_id": result_id, "campaign_id": campaign_id, "error": error}

    async def discard_prospect(self, result_id: str) -> dict[str, Any]:
        """Saca un lead de la cola de revision sin contactarlo — sigue en el
        CRM (ya se alimento con todo lo descubierto), solo deja de aparecer
        como pendiente de decision."""
        return await self._prospecting.mark_lead_stage(result_id, "DISCARDED")

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
