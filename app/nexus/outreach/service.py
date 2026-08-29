"""B2B outreach campaign manager for Nexus."""

from __future__ import annotations

import asyncio
import csv
import json
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from io import StringIO
from typing import Any

from agents.llm_router import LLMRouter
from nexus.prompts import resolve_prompt_sync
from nexus.outreach.repository import OutreachRepository
from nexus.outreach.transports import IMAPMailboxMonitor, SMTPOutreachTransport
from nexus.utils.llm_json import strip_llm_fences


class OutreachManager:
    """Creates, drafts and sends low-volume B2B outreach sequences."""

    def __init__(
        self,
        *,
        cfg,
        llm_router: LLMRouter | None,
        repository: OutreachRepository | None = None,
        smtp_transport: SMTPOutreachTransport | None = None,
        imap_monitor: IMAPMailboxMonitor | None = None,
    ) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._repository = repository or OutreachRepository(cfg.outreach_data_dir)
        self._smtp = smtp_transport or SMTPOutreachTransport(
            host=cfg.outreach_smtp_host,
            port=cfg.outreach_smtp_port,
            username=cfg.outreach_smtp_user,
            password=cfg.outreach_smtp_password,
        )
        self._imap = imap_monitor or IMAPMailboxMonitor(
            host=cfg.outreach_imap_host,
            port=cfg.outreach_imap_port,
            username=cfg.outreach_imap_user,
            password=cfg.outreach_imap_password,
        )

    async def status(self) -> dict[str, Any]:
        campaigns = await self._repository.load_campaigns()
        events = await self._repository.list_events(limit=25)
        smtp_status = await asyncio.to_thread(self._safe_healthcheck, self._smtp.healthcheck)
        imap_status = await asyncio.to_thread(self._safe_healthcheck, self._imap.healthcheck)
        today = datetime.now(timezone.utc).date().isoformat()
        sent_today = sum(1 for event in events if event.get("event_type") == "email_sent" and str(event.get("timestamp", "")).startswith(today))
        return {
            "status": "success",
            "enabled": self._cfg.outreach_enabled,
            "account": {
                "email": self._cfg.outreach_email_address,
                "sender_name": self._cfg.outreach_sender_name,
                "smtp": smtp_status,
                "imap": imap_status,
            },
            "daily_cap_default": self._cfg.outreach_daily_cap_default,
            "sent_today": sent_today,
            "campaigns_total": len(campaigns),
            "recent_campaigns": list(reversed(campaigns[-5:])),
            "recent_events": events,
        }

    async def launch_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        prospects = self._parse_prospects(payload)
        sender_name = (payload.get("sender_name") or self._cfg.outreach_sender_name or "").strip()
        if not sender_name:
            raise ValueError(
                "sender_name es obligatorio para lanzar una campaña. "
                "Configúralo en daily_config.json o en los ajustes de outreach."
            )
        campaign_id = f"out-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)
        followup_delays = payload.get("followup_delays_days") or self._default_followup_days()
        campaign = {
            "campaign_id": campaign_id,
            "campaign_name": payload["campaign_name"],
            "sender_name": sender_name,
            "sender_email": self._cfg.outreach_email_address,
            "proposition": payload["proposition"],
            "cta": payload.get("cta") or "¿Te viene bien una llamada de 15 minutos esta semana?",
            "audience_hint": payload.get("audience_hint") or "",
            "max_daily_send": int(payload.get("max_daily_send") or self._cfg.outreach_daily_cap_default),
            "followup_delays_days": followup_delays,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "prospects": [
                {
                    **prospect,
                    "prospect_id": f"pros-{uuid.uuid4().hex[:8]}",
                    "current_step": 0,
                    "status": "pending",
                    "history": [],
                    "next_due_at": now.isoformat(),
                }
                for prospect in prospects
            ],
        }
        campaigns = await self._repository.load_campaigns()
        campaigns.append(campaign)
        await self._repository.save_campaigns(campaigns)
        result = await self.run_campaign(campaign_id, dry_run=bool(payload.get("dry_run", True)))
        result["campaign_id"] = campaign_id
        result["total_prospects"] = len(prospects)
        return result

    async def run_campaign(self, campaign_id: str, *, dry_run: bool = True) -> dict[str, Any]:
        campaigns = await self._repository.load_campaigns()
        campaign = next((item for item in campaigns if item["campaign_id"] == campaign_id), None)
        if campaign is None:
            return {"status": "not_found", "campaign_id": campaign_id}

        due = self._collect_due_prospects(campaign)
        allowed = due[: campaign["max_daily_send"]]
        events: list[dict[str, Any]] = []
        for prospect in allowed:
            step_index = int(prospect["current_step"])
            draft = await self._draft_message(campaign, prospect, step_index)
            event = await self._deliver_or_preview(
                campaign=campaign,
                prospect=prospect,
                draft=draft,
                step_index=step_index,
                dry_run=dry_run,
            )
            prospect["history"].append(event)
            prospect["current_step"] = step_index + 1
            if prospect["current_step"] > len(campaign["followup_delays_days"]):
                prospect["status"] = "completed"
                prospect["next_due_at"] = None
            else:
                next_delay = campaign["followup_delays_days"][step_index]
                prospect["status"] = "waiting_followup"
                prospect["next_due_at"] = (datetime.now(timezone.utc) + timedelta(days=int(next_delay))).isoformat()
            events.append(event)
            await self._repository.append_event(event)

        campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._repository.save_campaigns(campaigns)
        return {
            "status": "accepted",
            "campaign_id": campaign_id,
            "dry_run": dry_run,
            "executed_count": len(events),
            "total_prospects": len(campaign["prospects"]),
            "events": events,
        }

    async def list_events(self, limit: int = 50) -> dict[str, Any]:
        events = await self._repository.list_events(limit=limit)
        return {"status": "success", "total": len(events), "events": events}

    async def list_campaigns(self, limit: int = 20) -> dict[str, Any]:
        campaigns = await self._repository.load_campaigns()
        recent = list(reversed(campaigns[-limit:]))
        return {"status": "success", "total": len(recent), "campaigns": recent}

    def _parse_prospects(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("prospects"):
            prospects = payload["prospects"]
        elif payload.get("csv_text"):
            prospects = self._parse_csv(payload["csv_text"])
        elif payload.get("json_text"):
            prospects = json.loads(payload["json_text"])
        else:
            raise ValueError("No se han proporcionado prospectos en CSV, JSON o lista.")

        cleaned: list[dict[str, Any]] = []
        for item in prospects:
            email = str(item.get("email", "")).strip()
            if "@" not in email:
                continue
            cleaned.append(
                {
                    "email": email,
                    "first_name": str(item.get("first_name", "")).strip(),
                    "company": str(item.get("company", "")).strip(),
                    "job_title": str(item.get("job_title", "")).strip(),
                    "company_domain": str(item.get("company_domain", "")).strip(),
                    "notes": str(item.get("notes", "")).strip(),
                    # Opcionales — solo presentes cuando el prospecto viene de una
                    # campana autonoma (ver CampaignAgent._map_prospect). Permiten
                    # personalizar el mensaje con un hallazgo real en vez de solo
                    # la proposition/cta generica de la campana.
                    "run_id": str(item.get("run_id", "")).strip(),
                    "result_id": str(item.get("result_id", "")).strip(),
                    "business_profile": item.get("business_profile") or {},
                    "proposal_items": item.get("proposal_items") or [],
                }
            )
        if not cleaned:
            raise ValueError("No hay prospectos válidos con email.")
        return cleaned

    def _parse_csv(self, csv_text: str) -> list[dict[str, Any]]:
        handle = StringIO(csv_text.strip())
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]

    def _collect_due_prospects(self, campaign: dict[str, Any]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        due: list[dict[str, Any]] = []
        for prospect in campaign["prospects"]:
            next_due_at = prospect.get("next_due_at")
            if prospect.get("status") == "completed" or not next_due_at:
                continue
            if datetime.fromisoformat(next_due_at) <= now:
                due.append(prospect)
        return due

    async def _draft_message(self, campaign: dict[str, Any], prospect: dict[str, Any], step_index: int) -> dict[str, str]:
        step_name = "contacto inicial" if step_index == 0 else f"follow-up {step_index}"
        if self._llm_router is None:
            return self._fallback_draft(campaign, prospect, step_index)

        first_name = (prospect.get("first_name") or "").strip()
        # Si el primer_name parece un email, descartarlo — es un error de importación
        if "@" in first_name or not first_name:
            nombre_instruccion = (
                "NO hay nombre del destinatario. "
                "Abre con 'Hola,' o directamente con el cuerpo. "
                "NUNCA uses el email, el dominio ni escribas 'sin nombre' como saludo."
            )
        else:
            nombre_instruccion = f"Nombre: {first_name}"

        # Limpiar historial: quitar campos que el LLM no necesita (evita que use el email como nombre)
        safe_history = [
            {k: v for k, v in event.items() if k in ("step_index", "subject", "body", "event_type", "timestamp")}
            for event in prospect.get("history", [])
        ]

        personalization = self._personalization_block(prospect)

        messages = [
            {"role": "system", "content": resolve_prompt_sync("outreach.system")},
            {
                "role": "user",
                "content": (
                    f"Redacta un {step_name} de prospección B2B.\n\n"
                    f"REMITENTE — firma obligatoria: {campaign['sender_name']}\n"
                    f"No uses '[Firma]' ni placeholders. El cuerpo debe terminar con el nombre real: {campaign['sender_name']}\n\n"
                    f"Propuesta de valor: {campaign['proposition']}\n"
                    f"CTA deseada: {campaign['cta']}\n"
                    f"Contexto de audiencia: {campaign.get('audience_hint') or 'despacho de asesoria fiscal y laboral'}\n\n"
                    f"Destinatario — {nombre_instruccion}\n"
                    f"Empresa: {prospect.get('company') or 'sin dato'}\n"
                    f"Cargo: {prospect.get('job_title') or 'sin dato'}\n"
                    f"Dominio: {prospect.get('company_domain') or 'sin dato'}\n"
                    f"Notas: {prospect.get('notes') or 'sin notas'}\n\n"
                    f"{personalization}"
                    f"Historial de contactos previos: {json.dumps(safe_history, ensure_ascii=False)}"
                ),
            },
        ]
        result = await self._llm_router.call(
            messages,
            min_level=0,
            preferred_level=1,
            speed_level=1,
            temperature=0.65,
            max_tokens=700,
        )
        if result.error:
            return self._fallback_draft(campaign, prospect, step_index)
        return self._parse_draft_content(result.content) or self._fallback_draft(campaign, prospect, step_index)

    def _personalization_block(self, prospect: dict[str, Any]) -> str:
        """Bloque opcional con hallazgo real + propuesta concreta, solo presente
        cuando el prospecto viene de una campana autonoma (ver
        CampaignAgent._map_prospect en prospecting/campaign_agent.py). Sin esto,
        el mensaje se apoya solo en la proposition/cta generica de la campana —
        este bloque es lo que permite el tono "he visto vuestra web y hay cosas
        mejorables" en vez de una plantilla generica.
        """
        profile = prospect.get("business_profile") or {}
        proposal_items = prospect.get("proposal_items") or []
        if not profile and not proposal_items:
            return ""

        lines = ["Hallazgo real sobre este negocio (usalo, no lo ignores ni lo generalices):"]
        what_they_do = str(profile.get("what_they_do") or "").strip()
        if what_they_do:
            lines.append(f"- Que hacen: {what_they_do}")
        friction = profile.get("friction_points") or []
        for item in friction[:2]:
            lines.append(f"- Friccion detectada: {item}")
        for item in proposal_items[:2]:
            observation = str(item.get("observation") or "").strip()
            recommendation = str(item.get("recommendation") or "").strip()
            if observation:
                lines.append(f"- Observacion concreta: {observation}")
            if recommendation:
                lines.append(f"- Propuesta concreta: {recommendation}")
        lines.append(
            "Usa como maximo UNO de estos hallazgos, el mas relevante, de forma natural — "
            "no los listes todos ni suenes a informe tecnico.\n"
        )
        return "\n".join(lines) + "\n\n"

    def _parse_draft_content(self, content: str) -> dict[str, str] | None:
        try:
            cleaned = strip_llm_fences(content)
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        subject = str(payload.get("subject", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not subject or not body:
            return None
        return {"subject": subject, "body": body}

    def _fallback_draft(self, campaign: dict[str, Any], prospect: dict[str, Any], step_index: int) -> dict[str, str]:
        company = prospect.get("company") or ""
        raw_name = (prospect.get("first_name") or "").strip()
        # Descartar si parece un email o está vacío
        saludo = raw_name if raw_name and "@" not in raw_name else ""
        apertura = f"{saludo},\n\n" if saludo else "Hola,\n\n"
        cierre = f"Un saludo,\n{campaign['sender_name']}"
        company_ref = f" en {company}" if company else ""

        if step_index == 0:
            subject = f"{campaign['proposition'][:50]}"
            body = (
                f"{apertura}"
                f"Me pongo en contacto porque trabajamos con despachos de asesoría en {campaign['proposition']}.\n\n"
                f"¿Te viene bien una llamada breve esta semana para ver si aplica a vuestro caso?\n\n"
                f"{cierre}"
            )
        else:
            subject = f"Re: {campaign['proposition'][:50]}"
            body = (
                f"{apertura}"
                f"Te escribo de nuevo sobre {campaign['proposition']}{company_ref}.\n\n"
                f"Si no es el momento adecuado, sin problema — dímelo y no vuelvo a molestar.\n\n"
                f"{cierre}"
            )
        return {"subject": subject, "body": body}

    async def _deliver_or_preview(
        self,
        *,
        campaign: dict[str, Any],
        prospect: dict[str, Any],
        draft: dict[str, str],
        step_index: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        event = {
            "event_id": f"evt-{uuid.uuid4().hex[:10]}",
            "event_type": "email_preview" if dry_run else "email_sent",
            "timestamp": timestamp,
            "campaign_id": campaign["campaign_id"],
            "campaign_name": campaign["campaign_name"],
            "recipient_email": prospect["email"],
            "recipient_name": prospect.get("first_name"),
            "company": prospect.get("company"),
            "step_index": step_index,
            "subject": draft["subject"],
            "body": draft["body"],
            "dry_run": dry_run,
        }
        if dry_run:
            event["delivery_status"] = "preview_only"
            return event

        message = EmailMessage()
        message["From"] = f"{campaign['sender_name']} <{campaign['sender_email']}>"
        message["To"] = prospect["email"]
        message["Subject"] = draft["subject"]
        message.set_content(draft["body"])
        delivery = await asyncio.to_thread(self._smtp.send, message)
        event["delivery_status"] = delivery.get("status", "unknown")
        return event

    def _default_followup_days(self) -> list[int]:
        values = []
        for item in str(self._cfg.outreach_followup_delays_days).split(","):
            item = item.strip()
            if item.isdigit():
                values.append(int(item))
        return values or [4, 9]

    @staticmethod
    def _safe_healthcheck(fn) -> dict[str, Any]:
        try:
            return fn()
        except Exception as exc:
            return {"configured": True, "status": "down", "reason": str(exc)}
