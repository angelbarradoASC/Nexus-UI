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
import uuid
from datetime import datetime, timedelta, timezone
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
_MESSAGE_FIELDS = "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,inferenceClassification,conversationId,webLink"

# Correos por llamada al LLM, y cuanto se deja descansar al LLM tras un fallo
# (429/cuota). Visto en vivo el 2026-10-01: 98 consultas en un dia, >=29 con
# todos los niveles en HTTP 429 (retry_after hasta ~37 min) porque se
# re-puntuaban los mismos 30 correos cada 5 minutos — cero avisos en todo el dia.
_LLM_CHUNK_SIZE = 10
_LLM_COOLDOWN = timedelta(minutes=10)
_MAX_CACHED_SCORES = 1000
_SCORING_MAX_TOKENS = 1500
# Anadido al prompt compartido mail.qualification (que no dice idioma ni
# longitud): sin esto las razones salian en ingles y de 200+ caracteres —
# visto en vivo — para un usuario hispanohablante, y agotaban max_tokens.
_SCORING_STYLE_SUFFIX = (
    "\n\nESTILO DE SALIDA: escribe `reason` y `suggested_action` SIEMPRE en español, "
    "en una sola frase corta (maximo 110 caracteres cada una). Devuelve un objeto por cada "
    "message_id recibido, copiando el message_id tal cual."
)


def _config_dir() -> Path:
    local_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Open-Nexus" / "config"
    local_root.mkdir(parents=True, exist_ok=True)
    return local_root


def _default_cache_path() -> Path:
    return _config_dir() / "outlook_token_cache.bin"


def _default_scores_path() -> Path:
    return _config_dir() / "outlook_scores.json"


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

    def __init__(self, cfg, llm_router=None, now_fn=None, token_store=None, http_transport=None, scores_path=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._token_store = token_store or OutlookTokenStore()
        # Inyectable en tests (httpx.MockTransport) para mockear SOLO Graph —
        # el cache de tokens (DPAPI/pywin32) se deja sin mockear a proposito,
        # tiene que funcionar de verdad, no solo en teoria.
        self._http_transport = http_transport
        # Puntuaciones ya hechas por message_id, persistidas: cada correo se
        # puntua UNA vez, no en cada consulta (ver _LLM_COOLDOWN arriba).
        self._scores_path = scores_path or _default_scores_path()
        self._scores: dict[str, dict[str, Any]] = self._load_scores()
        self._llm_cooldown_until: datetime | None = None

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

        self._apply_cached_scores(messages)
        self._apply_free_prefilter(messages)
        await self._score_pending_with_llm(messages)

        scored = sum(1 for m in messages if m["scored"])
        messages.sort(key=lambda m: (m.get("priority_score", 0), m.get("received_at", "")), reverse=True)
        total_limit = int(limit) if limit is not None else int(self._cfg.outlook_priority_total_limit)
        return {
            "status": "success",
            "messages": messages[:total_limit],
            "checked_at": self._now_fn().isoformat(),
            # degraded=True => hay correos sin puntuar (LLM caido/en cooldown):
            # quien muestre el resultado NO debe presentar "low" como si fuera
            # un veredicto — significa "no lo se todavia".
            "scoring": {"scored": scored, "unscored": len(messages) - scored, "degraded": scored < len(messages)},
        }

    # ── Puntuacion: cache + prefiltro gratis + LLM solo para lo nuevo ────────

    def _apply_cached_scores(self, messages: list[dict[str, Any]]) -> None:
        for m in messages:
            cached = self._scores.get(m["message_id"])
            if cached:
                m.update(cached)
                m["scored"] = True

    def _apply_free_prefilter(self, messages: list[dict[str, Any]]) -> None:
        """La bandeja "Otros" de Outlook (inferenceClassification, el filtro de
        Microsoft para promociones/newsletters) no merece una llamada al LLM
        ni una interrupcion — salvo que el remitente la marcara como alta
        importancia. Gratis y sin cuota; es justo lo que el usuario pedia
        (Instagram/newsletters mezclados con correos reales)."""
        changed = False
        for m in messages:
            if m["scored"] or m.get("inference") != "other" or m.get("graph_importance") == "high":
                continue
            m.update(
                priority_score=0,
                importance="low",
                reason="Bandeja 'Otros' de Outlook (promoción/newsletter).",
                suggested_action="ignorar",
                scored=True,
            )
            self._remember_score(m)
            changed = True
        if changed:
            self._save_scores()

    async def _score_pending_with_llm(self, messages: list[dict[str, Any]]) -> None:
        pending = [m for m in messages if not m["scored"]]
        if not pending or self._llm_router is None:
            return
        now = self._now_fn()
        if self._llm_cooldown_until is not None and now < self._llm_cooldown_until:
            return  # el LLM acaba de fallar — no martillearlo, se reintenta pasado el cooldown

        for start in range(0, len(pending), _LLM_CHUNK_SIZE):
            chunk = pending[start:start + _LLM_CHUNK_SIZE]
            try:
                await self._enrich_with_llm(chunk)
            except Exception as exc:
                self._llm_cooldown_until = now + _LLM_COOLDOWN
                logger.warning(
                    "OutlookMailManager | puntuacion LLM fallida ({}) — {} correos sin puntuar, "
                    "reintento tras {} min",
                    str(exc)[:120], len(pending) - start, int(_LLM_COOLDOWN.total_seconds() // 60),
                )
                break
            for m in chunk:
                if m["scored"]:
                    self._remember_score(m)
        self._save_scores()

    def _remember_score(self, m: dict[str, Any]) -> None:
        self._scores[m["message_id"]] = {
            "priority_score": m["priority_score"],
            "importance": m["importance"],
            "reason": m["reason"],
            "suggested_action": m["suggested_action"],
        }
        while len(self._scores) > _MAX_CACHED_SCORES:
            self._scores.pop(next(iter(self._scores)))

    def _load_scores(self) -> dict[str, dict[str, Any]]:
        try:
            if self._scores_path.exists():
                data = json.loads(self._scores_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            logger.warning("OutlookMailManager | cache de puntuaciones ilegible — se empieza vacia")
        return {}

    def _save_scores(self) -> None:
        try:
            tmp_path = self._scores_path.with_suffix(f".tmp-{uuid.uuid4().hex[:8]}")
            tmp_path.write_text(json.dumps(self._scores, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self._scores_path)
        except Exception:
            logger.warning("OutlookMailManager | no se pudo guardar la cache de puntuaciones")

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
        system_prompt = resolve_prompt_sync("mail.qualification") + _SCORING_STYLE_SUFFIX
        # IDs cortos hacia el LLM ("m1".."m10"), no el id de Graph: son ~150
        # caracteres de base64 que el modelo tiene que repetir en SU salida —
        # con 6 correos la respuesta se truncaba a mitad de JSON en max_tokens
        # (visto en vivo, 2026-10-16: LEN 1896, JSONDecodeError) y esos
        # correos quedaban sin puntuar para siempre, reintentados cada ciclo.
        short_to_message = {f"m{i + 1}": m for i, m in enumerate(messages)}
        # preview recortado SOLO para este payload (no se toca el preview
        # que se le muestra al usuario): 160 caracteres bastan para juzgar
        # importancia (el payload completo causo los HTTP 413 vistos en vivo).
        payload = [
            {
                "message_id": short_id,
                "sender_name": m["sender_name"],
                "sender_email": m["sender_email"],
                "subject": m["subject"],
                "preview": (m["preview"] or "")[:160],
                "unread": m["unread"],
                "importance": m.get("graph_importance", "normal"),
            }
            for short_id, m in short_to_message.items()
        ]
        response = await self._llm_router.call(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=_SCORING_MAX_TOKENS,
            temperature=0.1,
        )
        if response.error:
            raise RuntimeError(response.error)

        try:
            qualified = json.loads(strip_llm_fences(response.content))
        except json.JSONDecodeError as exc:
            # Antes: `return messages` en silencio. Un JSON ilegible (truncado,
            # texto suelto) es un fallo del LLM como otro cualquiera: se
            # registra y activa el enfriamiento en vez de reintentarse ciegamente.
            raise RuntimeError(f"respuesta de puntuacion no parseable ({len(response.content or '')} caracteres): {exc}") from exc

        by_id = {item.get("message_id"): item for item in qualified if isinstance(item, dict)}
        for short_id, m in short_to_message.items():
            update = by_id.get(short_id)
            if not update:
                continue
            m["priority_score"] = int(update.get("score", 0))
            m["importance"] = update.get("importance", "low")
            m["reason"] = update.get("reason", "")
            m["suggested_action"] = update.get("suggested_action", "leer")
            m["scored"] = True
        return messages

    @staticmethod
    def _clean_preview(raw_preview: str) -> str:
        """bodyPreview de Graph trae a veces saltos de linea/espacios sueltos
        de HTML mal convertido a texto — se colapsa a una sola linea legible,
        igual que ya hace ThunderbirdMailManager con el correo de
        Thunderbird (_extract_preview), y se recorta a un tamaño razonable
        para mostrar en chat/UI."""
        collapsed = " ".join((raw_preview or "").split())
        return collapsed[:400]

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
            "preview": OutlookMailManager._clean_preview(raw.get("bodyPreview") or ""),
            "received_at": raw.get("receivedDateTime"),
            "unread": not raw.get("isRead", True),
            "graph_importance": raw.get("importance", "normal"),
            "inference": raw.get("inferenceClassification", "focused"),
            "conversation_id": raw.get("conversationId") or "",
            "web_link": raw.get("webLink", ""),
            "priority_score": 0,
            "importance": "low",
            "reason": "",
            "suggested_action": "leer",
            # False = todavia sin veredicto (no confundir con "puntuado como low")
            "scored": False,
        }
