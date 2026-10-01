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

from loguru import logger

from agents.llm_router import LLMRouter
from agents.tools.credential_store import CredentialStore
from nexus.prompts import resolve_prompt_sync
from nexus.outreach.repository import OutreachRepository
from nexus.outreach.transports import IMAPMailboxMonitor, SMTPOutreachTransport
from nexus.utils.llm_json import strip_llm_fences

# Prefijo de clave en CredentialStore (data/credentials.enc) para cuentas
# SMTP reales de outreach — nunca "una sola cuenta global", una por vía
# (automato / sls_assetsconsultores). Ver
# scripts/export_outreach_smtp_credentials.py.
_ACCOUNT_KEY_PREFIX = "outreach_smtp:"
_IMAP_ACCOUNT_KEY_PREFIX = "outreach_imap:"


class OutreachManager:
    """Creates, drafts and sends low-volume B2B outreach sequences."""

    def __init__(
        self,
        *,
        cfg,
        llm_router: LLMRouter | None,
        repository: OutreachRepository | None = None,
        credential_store: CredentialStore | None = None,
        imap_monitor: IMAPMailboxMonitor | None = None,
        transport_factory: Any = None,
        imap_monitor_factory: Any = None,
    ) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._repository = repository or OutreachRepository(cfg.outreach_data_dir)
        self._credentials = credential_store or CredentialStore()
        self._transport_factory = transport_factory or SMTPOutreachTransport
        self._transports: dict[str, SMTPOutreachTransport] = {}
        self._imap_monitor_factory = imap_monitor_factory or IMAPMailboxMonitor
        self._imap_monitors: dict[str, IMAPMailboxMonitor] = {}
        self._imap = imap_monitor or IMAPMailboxMonitor(
            host=cfg.outreach_imap_host,
            port=cfg.outreach_imap_port,
            username=cfg.outreach_imap_user,
            password=cfg.outreach_imap_password,
        )
        # Cursor de rotacion round-robin, uno por cada pool de cuentas distinto
        # (una linea de campaña con varias outreach_accounts) — vive en memoria,
        # igual que _transports/_imap_monitors: se reinicia con el proceso, lo
        # cual es inofensivo (solo reinicia el reparto, nunca envia de mas ni
        # de menos). Clave = tupla ordenada de account_key, para que dos lineas
        # con el mismo pool compartan contador y lineas distintas no se pisen.
        self._rotation_cursor: dict[tuple[str, ...], int] = {}

    def _account_creds(self, account_key: str) -> dict[str, Any] | None:
        return self._credentials.get(f"{_ACCOUNT_KEY_PREFIX}{account_key}")

    def _account_email(self, account_key: str) -> str:
        return (self._account_creds(account_key) or {}).get("email", "")

    def _transport_for(self, account_key: str) -> SMTPOutreachTransport:
        if account_key not in self._transports:
            creds = self._account_creds(account_key)
            if not creds:
                raise ValueError(
                    f"No hay credenciales SMTP guardadas para la cuenta outreach '{account_key}'. "
                    "Ejecuta scripts/export_outreach_smtp_credentials.py."
                )
            self._transports[account_key] = self._transport_factory(
                host=creds["host"],
                port=int(creds.get("port", 465)),
                username=creds["user"],
                password=creds["password"],
            )
        return self._transports[account_key]

    def _known_account_keys(self) -> list[str]:
        return sorted(
            key[len(_ACCOUNT_KEY_PREFIX):]
            for key in self._credentials.list_hosts()
            if key.startswith(_ACCOUNT_KEY_PREFIX)
        )

    def list_accounts(self) -> list[dict[str, str]]:
        """Cuentas reales disponibles para elegir como outreach_account de
        una línea — extraídas de Thunderbird (scripts/export_outreach_smtp_
        credentials.py), nunca inventadas ni tecleadas a mano."""
        return [
            {"account_key": key, "email": self._account_email(key)}
            for key in self._known_account_keys()
        ]

    async def pick_account(self, candidates: list[str]) -> str:
        """Elige UNA cuenta real entre varias candidatas de una misma línea
        (outreach_accounts) — antes cada línea tenía una única cuenta fija
        (outreach_account), así que todo el volumen de esa línea salía
        siempre de la misma bandeja. Con varias cuentas candidatas:
        1. descarta las que no tengan credenciales guardadas
        2. descarta las que fallen el healthcheck SMTP real (misma
           comprobación que ya usa status() para el panel de Agentes/Mail)
        3. reparte en round-robin entre las que queden sanas — nunca elige
           siempre la primera, para no acabar enviando todo por una cuenta
           solo porque es la primera de la lista

        Con un único candidato (el caso normal hoy, listas de 1 elemento)
        se comporta igual que antes: lo verifica y lo usa si esta sano.
        """
        pool = [key for key in candidates if key]
        if not pool:
            raise ValueError(
                "No hay ninguna cuenta de envío configurada para esta línea "
                "(outreach_account / outreach_accounts vacíos)."
            )
        configured = [key for key in pool if self._account_creds(key)]
        if not configured:
            raise ValueError(
                f"Ninguna de las cuentas configuradas ({', '.join(pool)}) tiene "
                "credenciales guardadas. Ejecuta scripts/export_outreach_smtp_credentials.py."
            )
        healthy: list[str] = []
        unhealthy: list[str] = []
        for key in configured:
            try:
                transport = self._transport_for(key)
                result = await asyncio.to_thread(self._safe_healthcheck, transport.healthcheck)
            except Exception:
                unhealthy.append(key)
                continue
            # "up" es el unico estado realmente sano — "not_configured"
            # (sin credenciales, no deberia llegar aqui tras el filtro de
            # arriba pero por si acaso) y "down" (_safe_healthcheck atrapando
            # una excepcion real de conexion) cuentan igual como no usable.
            if result.get("status") != "up":
                unhealthy.append(key)
            else:
                healthy.append(key)
        if unhealthy:
            logger.warning("Cuentas de envío descartadas por healthcheck fallido: {}", unhealthy)
        if not healthy:
            raise ValueError(
                f"Ninguna cuenta sana entre las candidatas ({', '.join(configured)}) — "
                "todas fallaron el healthcheck SMTP."
            )
        pool_key = tuple(sorted(healthy))
        index = self._rotation_cursor.get(pool_key, 0) % len(healthy)
        self._rotation_cursor[pool_key] = index + 1
        return healthy[index]

    def _imap_creds(self, account_key: str) -> dict[str, Any] | None:
        return self._credentials.get(f"{_IMAP_ACCOUNT_KEY_PREFIX}{account_key}")

    def _imap_monitor_for(self, account_key: str) -> IMAPMailboxMonitor | None:
        if account_key not in self._imap_monitors:
            creds = self._imap_creds(account_key)
            if not creds:
                return None
            self._imap_monitors[account_key] = self._imap_monitor_factory(
                host=creds["host"],
                port=int(creds.get("port", 993)),
                username=creds["user"],
                password=creds["password"],
            )
        return self._imap_monitors[account_key]

    async def check_replies(self, account_key: str) -> list[dict[str, Any]]:
        """Comprueba respuestas REALES en la bandeja de la cuenta que envia
        esta linea — solo mira prospectos activos (pending/waiting_followup)
        de campañas lanzadas con esa cuenta. Al detectar una respuesta real
        (fecha posterior al ultimo contacto), para los follow-ups de ese
        prospecto (mismo mecanismo que 'completed', next_due_at a None) y
        registra el evento — nunca se sigue insistiendo a quien ya
        contesto."""
        imap = self._imap_monitor_for(account_key)
        if imap is None:
            return []

        campaigns = await self._repository.load_campaigns()
        relevant = [c for c in campaigns if c.get("outreach_account") == account_key]
        if not relevant:
            return []

        active: dict[str, tuple[dict[str, Any], dict[str, Any], datetime]] = {}
        for campaign in relevant:
            for prospect in campaign.get("prospects", []):
                if prospect.get("status") in ("completed", "replied"):
                    continue
                email = (prospect.get("email") or "").strip().lower()
                if not email:
                    continue
                history = prospect.get("history") or []
                last_contact = history[-1]["timestamp"] if history else campaign.get("created_at")
                if not last_contact:
                    continue
                active[email] = (campaign, prospect, datetime.fromisoformat(last_contact))

        if not active:
            return []

        earliest_since = min(since for _, _, since in active.values())
        found = await asyncio.to_thread(
            imap.find_replies, from_addresses=list(active.keys()), since=earliest_since,
        )

        reply_events: list[dict[str, Any]] = []
        for email, received_at in found.items():
            campaign, prospect, since = active.get(email, (None, None, None))
            if prospect is None or datetime.fromisoformat(received_at) <= since:
                continue
            prospect["status"] = "replied"
            prospect["next_due_at"] = None
            event = {
                "event_id": f"evt-{uuid.uuid4().hex[:10]}",
                "event_type": "reply_detected",
                "timestamp": received_at,
                "campaign_id": campaign["campaign_id"],
                "campaign_name": campaign["campaign_name"],
                "recipient_email": email,
                "company": prospect.get("company"),
            }
            prospect.setdefault("history", []).append(event)
            await self._repository.append_event(event)
            reply_events.append(event)

        if reply_events:
            await self._repository.save_campaigns(campaigns)
        return reply_events

    async def status(self) -> dict[str, Any]:
        campaigns = await self._repository.load_campaigns()
        events = await self._repository.list_events(limit=25)
        accounts_status: dict[str, Any] = {}
        for account_key in self._known_account_keys():
            try:
                transport = self._transport_for(account_key)
                smtp_status = await asyncio.to_thread(self._safe_healthcheck, transport.healthcheck)
            except Exception as exc:
                smtp_status = {"configured": False, "status": "error", "error": str(exc)}
            accounts_status[account_key] = {"email": self._account_email(account_key), "smtp": smtp_status}
        imap_status = await asyncio.to_thread(self._safe_healthcheck, self._imap.healthcheck)
        today = datetime.now(timezone.utc).date().isoformat()
        sent_today = sum(1 for event in events if event.get("event_type") == "email_sent" and str(event.get("timestamp", "")).startswith(today))
        return {
            "status": "success",
            "enabled": self._cfg.outreach_enabled,
            "accounts": accounts_status,
            "imap": imap_status,
            "daily_cap_default": self._cfg.outreach_daily_cap_default,
            "sent_today": sent_today,
            "campaigns_total": len(campaigns),
            "recent_campaigns": list(reversed(campaigns[-5:])),
            "recent_events": events,
        }

    async def launch_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        prospects = self._parse_prospects(payload)
        outreach_account = (payload.get("outreach_account") or "").strip()
        if not outreach_account:
            raise ValueError(
                "outreach_account es obligatorio para lanzar una campaña — qué "
                "cuenta real envía (p.ej. 'automato', 'sls_assetsconsultores'). "
                "Configúralo en la línea de daily_config.json."
            )
        sender_email = self._account_email(outreach_account)
        if not sender_email:
            raise ValueError(
                f"No hay credenciales guardadas para la cuenta outreach '{outreach_account}'. "
                "Ejecuta scripts/export_outreach_smtp_credentials.py."
            )
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
            "sender_email": sender_email,
            "outreach_account": outreach_account,
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
        transport = self._transport_for(campaign.get("outreach_account", ""))
        delivery = await asyncio.to_thread(transport.send, message)
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
