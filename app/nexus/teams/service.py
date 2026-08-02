"""Microsoft Teams chat polling via Microsoft Graph, using MSAL PKCE.

Desktop no expone ningun endpoint publico, asi que no usa un bot real de
Teams (Bot Framework, que necesita que Microsoft le empuje mensajes a una
URL publica). En su lugar, sondea hacia fuera con permisos delegados del
usuario que ha iniciado sesion (Chat.Read, ChatMessage.Send), igual que
el correo hace con IMAP: Desktop pregunta, nadie le empuja nada.
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

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["Chat.Read", "ChatMessage.Send"]


def _default_cache_path() -> Path:
    local_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Open-Nexus" / "config"
    local_root.mkdir(parents=True, exist_ok=True)
    return local_root / "teams_token_cache.bin"


class TeamsAuthError(RuntimeError):
    """Raised when no valid Teams/Graph token is available."""


class TeamsTokenStore:
    """Persiste el token cache de MSAL cifrado con DPAPI en un fichero local.

    Windows Credential Manager (via keyring) tiene un limite de ~2.5KB por
    entrada, y un cache de MSAL con id/access/refresh token lo supera con
    facilidad (WinError 1783). msal-extensions usa el mismo cifrado ligado
    al usuario de Windows (DPAPI) pero sin ese limite de tamano.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_cache_path()

    def build_cache(self) -> msal_extensions.PersistedTokenCache:
        persistence = msal_extensions.build_encrypted_persistence(str(self._path))
        return msal_extensions.PersistedTokenCache(persistence)


class TeamsChatManager:
    """Reads Microsoft Teams chats via Graph API, on behalf of the signed-in user."""

    def __init__(self, cfg, llm_router=None, now_fn=None, case_log=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._token_store = TeamsTokenStore()
        self._case_log = case_log

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

        MSAL monta su propio servidor local efimero para capturar la
        redireccion OAuth — no puede usar el puerto 11430, que ya ocupa
        el propio Nexus. Se apoya en que el App Registration tiene
        registrado "http://localhost" (sin puerto fijo), que Azure AD
        acepta para cualquier puerto en clientes publicos.
        """
        app = self._build_app()
        result = app.acquire_token_interactive(scopes=_SCOPES)
        if "access_token" not in result:
            raise TeamsAuthError(result.get("error_description", "Login interactivo fallido."))
        accounts = app.get_accounts()
        return {
            "status": "success",
            "account": accounts[0]["username"] if accounts else None,
        }

    # ── API publica ─────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        if not self._cfg.teams_enabled:
            return {"status": "disabled", "reason": "Teams desactivado en esta instancia."}
        token = self._acquire_token_silent()
        if token is None:
            return {
                "status": "not_authenticated",
                "reason": "No hay sesion de Microsoft activa. Requiere login interactivo (POST /api/nexus/teams/login).",
            }
        app = self._build_app()
        accounts = app.get_accounts()
        return {
            "status": "success",
            "account": accounts[0]["username"] if accounts else None,
        }

    async def get_priority_messages(self, limit: int | None = None) -> dict[str, Any]:
        if not self._cfg.teams_enabled:
            return {"status": "disabled", "messages": []}
        token = self._acquire_token_silent()
        if token is None:
            return {"status": "not_authenticated", "messages": []}

        headers = {"Authorization": f"Bearer {token}"}
        per_chat_limit = int(self._cfg.teams_message_limit_per_chat)
        messages: list[dict[str, Any]] = []

        async with httpx.AsyncClient(base_url=_GRAPH_BASE, headers=headers, timeout=20.0) as client:
            # Graph rechaza $orderby=lastUpdatedDateTime en /me/chats ("QueryOptions
            # to order by 'lastUpdatedDateTime' is not supported."). Se ordena en
            # Python mas abajo, por created_at de cada mensaje.
            chats_resp = await client.get("/me/chats", params={"$top": 50})
            chats_resp.raise_for_status()
            chats = chats_resp.json().get("value", [])

            for chat in chats:
                chat_id = chat.get("id")
                topic = chat.get("topic") or chat.get("chatType", "chat")
                try:
                    msgs_resp = await client.get(
                        f"/chats/{chat_id}/messages",
                        params={"$top": per_chat_limit},
                    )
                    msgs_resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    messages.append({"chat_id": chat_id, "chat_topic": topic, "error": str(exc)})
                    continue
                for raw_message in msgs_resp.json().get("value", []):
                    parsed = self._parse_message(chat_id, topic, raw_message)
                    if parsed:
                        messages.append(parsed)

        messages.sort(key=lambda m: m.get("created_at") or "", reverse=True)
        total_limit = int(limit) if limit is not None else int(self._cfg.teams_priority_total_limit)
        return {
            "status": "success",
            "messages": messages[:total_limit],
            "checked_at": self._now_fn().isoformat(),
        }

    # ── Envio y respuesta con LLM ────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        """Envia un mensaje de texto a un chat de Teams, en nombre del usuario logueado."""
        if not self._cfg.teams_enabled:
            return {"status": "disabled"}
        token = self._acquire_token_silent()
        if token is None:
            return {"status": "not_authenticated"}

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=_GRAPH_BASE, headers=headers, timeout=20.0) as client:
            resp = await client.post(
                f"/chats/{chat_id}/messages",
                json={"body": {"contentType": "text", "content": text}},
            )
            resp.raise_for_status()
            sent = resp.json()

        return {
            "status": "success",
            "message_id": sent.get("id"),
            "created_at": sent.get("createdDateTime"),
        }

    async def respond_to_message(self, chat_id: str, message_text: str, sender_name: str = "") -> dict[str, Any]:
        """Contesta de inmediato a un mensaje entrante, analizado por LLM.

        Prioriza velocidad: genera y envia una respuesta breve enseguida
        (aunque sea para dar largas: "estoy en ello, dame un momento"),
        en vez de dejar al usuario esperando mientras se hace un analisis
        mas profundo (eso queda para el "ticket PEPO", todavia por definir).
        """
        case_id = f"teams:{chat_id}"
        if self._case_log is not None:
            self._case_log.log(
                case_id,
                kind="mensaje_usuario",
                actor="usuario",
                summary=message_text[:200],
                details={"sender_name": sender_name, "chat_id": chat_id},
            )

        holding_reply = await self._generate_holding_reply(message_text, sender_name)
        send_result = await self.send_message(chat_id, holding_reply)

        if self._case_log is not None:
            self._case_log.log(
                case_id,
                kind="mensaje_pepo",
                actor="pepo",
                summary=holding_reply[:200],
                details={"chat_id": chat_id, "send_result": send_result},
            )

        return {
            "status": send_result.get("status", "error"),
            "reply_text": holding_reply,
            "send_result": send_result,
        }

    async def _generate_holding_reply(self, message_text: str, sender_name: str) -> str:
        if self._llm_router is None:
            return "He recibido tu mensaje, estoy en ello. Te contesto en breve."

        system_prompt = resolve_prompt_sync("pepo.teams_holding_reply")
        payload = json.dumps({"sender_name": sender_name, "message": message_text}, ensure_ascii=False)
        try:
            response = await self._llm_router.call(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload},
                ],
                max_tokens=120,
                temperature=0.4,
            )
        except Exception:
            logger.exception("DEBUG teams | fallo generando respuesta de espera con LLM")
            return "He recibido tu mensaje, estoy en ello. Te contesto en breve."

        if response.error or not response.content.strip():
            return "He recibido tu mensaje, estoy en ello. Te contesto en breve."
        return response.content.strip()

    @staticmethod
    def _parse_message(chat_id: str, chat_topic: str, raw: dict[str, Any]) -> dict[str, Any] | None:
        body = raw.get("body") or {}
        content = (body.get("content") or "").strip()
        if not content:
            return None
        from_user = ((raw.get("from") or {}).get("user")) or {}
        return {
            "message_id": f"{chat_id}:{raw.get('id')}",
            "chat_id": chat_id,
            "chat_topic": chat_topic,
            "sender_name": from_user.get("displayName", ""),
            "sender_id": from_user.get("id", ""),
            "preview": content[:500],
            "created_at": raw.get("createdDateTime"),
            "message_type": raw.get("messageType", "message"),
        }
