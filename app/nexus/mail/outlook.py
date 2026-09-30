"""Outlook (Microsoft 365) mail access via Microsoft Graph, using MSAL PKCE.

Mismo patron que app/nexus/teams/service.py (TeamsChatManager) — mismo
proveedor (Graph), mismo mecanismo de auth (MSAL PublicClientApplication
con PKCE, cache de tokens cifrado con DPAPI via msal_extensions), distinto
recurso (mail en vez de chats). Cache de tokens propio (outlook_token_
cache.bin) — reconectar Outlook no afecta a la sesion de Teams ni viceversa.

Lectura + puntuacion de prioridad reutiliza el prompt "mail.qualification"
que ya usa ThunderbirdMailManager (app/nexus/mail/service.py) — mismo
formato de salida {message_id, score, importance, reason, suggested_action},
sin inventar un segundo esquema de clasificacion.

Enviar (reply/send) es una accion real sobre el correo de un tercero — a
diferencia del "holding reply" automatico de Teams, aqui PEPO nunca envia
sin que el usuario lo pida explicitamente en la conversacion (ver skill
mail.outlook_reply, nivel OPERATE con confirmacion obligatoria).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import msal
import msal_extensions
from loguru import logger

from nexus.prompts import resolve_prompt_sync
from nexus.utils.llm_json import strip_llm_fences

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["Mail.Read", "Mail.Send"]
_MESSAGE_FIELDS = "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,webLink"


def _default_cache_path() -> Path:
    local_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Open-Nexus" / "config"
    local_root.mkdir(parents=True, exist_ok=True)
    return local_root / "outlook_token_cache.bin"


class OutlookAuthError(RuntimeError):
    """Raised when no valid Outlook/Graph token is available."""


class OutlookTokenStore:
    """Persiste el token cache de MSAL cifrado con DPAPI — mismo mecanismo
    que TeamsTokenStore, fichero propio para no compartir sesion con Teams."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_cache_path()

    def build_cache(self) -> msal_extensions.PersistedTokenCache:
        persistence = msal_extensions.build_encrypted_persistence(str(self._path))
        return msal_extensions.PersistedTokenCache(persistence)


class OutlookMailManager:
    """Reads and replies to Outlook mail via Graph API, on behalf of the signed-in user."""

    def __init__(self, cfg, llm_router=None, now_fn=None, token_store=None, http_transport=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._token_store = token_store or OutlookTokenStore()
        # Inyectable en tests (httpx.MockTransport) para mockear SOLO Graph —
        # el cache de tokens (DPAPI/pywin32) se deja sin mockear a proposito,
        # tiene que funcionar de verdad, no solo en teoria.
        self._http_transport = http_transport

    # ── Autenticacion ────────────────────────────────────────────────────────

    def _build_app(self) -> msal.PublicClientApplication:
        cache = self._token_store.build_cache()
        authority = f"https://login.microsoftonline.com/{self._cfg.azure_tenant_id}"
        return msal.PublicClientApplication(
            self._cfg.azure_client_id,
            authority=authority,
            token_cache=cache,
        )

    def _acquire_token_silent(self) -> str | None:
        app = self._build_app()
        accounts = app.get_accounts()
        if not accounts:
            return None
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]
        return None

    def start_interactive_login(self) -> dict[str, Any]:
        """Lanza un login interactivo (abre el navegador). Bloqueante hasta completarse.

        Mismo mecanismo que Teams: MSAL monta su propio servidor local
        efimero para la redireccion OAuth, apoyado en que el App
        Registration tiene "http://localhost" (sin puerto fijo) registrado.
        """
        app = self._build_app()
        result = app.acquire_token_interactive(scopes=_SCOPES)
        if "access_token" not in result:
            raise OutlookAuthError(result.get("error_description", "Login interactivo fallido."))
        accounts = app.get_accounts()
        return {
            "status": "success",
            "account": accounts[0]["username"] if accounts else None,
        }

    def _graph_client(self, headers: dict[str, str]) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=_GRAPH_BASE, headers=headers, timeout=20.0, transport=self._http_transport)

    # ── API publica ─────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        if not self._cfg.outlook_enabled:
            return {"status": "disabled", "reason": "Outlook desactivado en esta instancia."}
        token = self._acquire_token_silent()
        if token is None:
            return {
                "status": "not_authenticated",
                "reason": "No hay sesion de Microsoft activa. Requiere login interactivo (POST /api/nexus/outlook/login).",
            }
        app = self._build_app()
        accounts = app.get_accounts()
        return {
            "status": "success",
            "account": accounts[0]["username"] if accounts else None,
        }

    async def get_priority_messages(self, limit: int | None = None) -> dict[str, Any]:
        if not self._cfg.outlook_enabled:
            return {"status": "disabled", "messages": []}
        token = self._acquire_token_silent()
        if token is None:
            return {"status": "not_authenticated", "messages": []}

        headers = {"Authorization": f"Bearer {token}"}
        message_limit = int(self._cfg.outlook_message_limit)

        async with self._graph_client(headers) as client:
            resp = await client.get(
                "/me/mailFolders/inbox/messages",
                params={
                    "$top": message_limit,
                    "$select": _MESSAGE_FIELDS,
                    "$orderby": "receivedDateTime desc",
                },
            )
            resp.raise_for_status()
            raw_messages = resp.json().get("value", [])

        messages = [self._parse_message(m) for m in raw_messages]
        messages = [m for m in messages if m]

        if self._llm_router is not None and messages:
            try:
                messages = await self._enrich_with_llm(messages)
            except Exception:
                logger.exception("OutlookMailManager | fallo puntuando prioridad con LLM")

        messages.sort(key=lambda m: (m.get("priority_score", 0), m.get("received_at", "")), reverse=True)
        total_limit = int(limit) if limit is not None else int(self._cfg.outlook_priority_total_limit)
        return {
            "status": "success",
            "messages": messages[:total_limit],
            "checked_at": self._now_fn().isoformat(),
        }

    async def send_reply(self, message_id: str, body: str) -> dict[str, Any]:
        """Responde DENTRO del hilo real de un correo existente — nunca crea
        un mensaje suelto. Exige message_id real devuelto por
        get_priority_messages(), nunca lo inventa el LLM."""
        if not self._cfg.outlook_enabled:
            return {"status": "disabled"}
        token = self._acquire_token_silent()
        if token is None:
            return {"status": "not_authenticated"}

        headers = {"Authorization": f"Bearer {token}"}
        async with self._graph_client(headers) as client:
            resp = await client.post(
                f"/me/messages/{message_id}/reply",
                json={"comment": body},
            )
            resp.raise_for_status()

        return {"status": "success", "message_id": message_id}

    async def send_new(self, *, to: str, subject: str, body: str) -> dict[str, Any]:
        """Envia un correo nuevo (no una respuesta a un hilo existente)."""
        if not self._cfg.outlook_enabled:
            return {"status": "disabled"}
        token = self._acquire_token_silent()
        if token is None:
            return {"status": "not_authenticated"}

        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            }
        }
        async with self._graph_client(headers) as client:
            resp = await client.post("/me/sendMail", json=payload)
            resp.raise_for_status()

        return {"status": "success", "to": to}

    # ── Puntuacion de prioridad (LLM) ────────────────────────────────────────

    async def _enrich_with_llm(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system_prompt = resolve_prompt_sync("mail.qualification")
        payload = [
            {
                "message_id": m["message_id"],
                "sender_name": m["sender_name"],
                "sender_email": m["sender_email"],
                "subject": m["subject"],
                "preview": m["preview"],
                "unread": m["unread"],
                "importance": m.get("graph_importance", "normal"),
            }
            for m in messages
        ]
        response = await self._llm_router.call(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if response.error:
            raise RuntimeError(response.error)

        content = strip_llm_fences(response.content)
        try:
            qualified = json.loads(content)
        except json.JSONDecodeError:
            return messages

        by_id = {item.get("message_id"): item for item in qualified if isinstance(item, dict)}
        for m in messages:
            update = by_id.get(m.get("message_id"))
            if not update:
                continue
            m["priority_score"] = int(update.get("score", 0))
            m["importance"] = update.get("importance", "low")
            m["reason"] = update.get("reason", "")
            m["suggested_action"] = update.get("suggested_action", "leer")
        return messages

    @staticmethod
    def _parse_message(raw: dict[str, Any]) -> dict[str, Any] | None:
        message_id = raw.get("id")
        if not message_id:
            return None
        from_field = (raw.get("from") or {}).get("emailAddress") or {}
        subject = raw.get("subject") or "(sin asunto)"
        return {
            "message_id": message_id,
            "sender_name": from_field.get("name", ""),
            "sender_email": from_field.get("address", ""),
            "subject": subject,
            "preview": (raw.get("bodyPreview") or "").strip(),
            "received_at": raw.get("receivedDateTime"),
            "unread": not raw.get("isRead", True),
            "graph_importance": raw.get("importance", "normal"),
            "web_link": raw.get("webLink", ""),
            "priority_score": 0,
            "importance": "low",
            "reason": "",
            "suggested_action": "leer",
        }
