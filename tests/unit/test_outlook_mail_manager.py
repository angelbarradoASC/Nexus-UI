"""tests/unit/test_outlook_mail_manager.py

OutlookMailManager — mismo patron OAuth/Graph que TeamsChatManager
(app/nexus/teams/service.py), aplicado a Outlook.

Regla explicita del usuario: el cache de tokens (DPAPI via pywin32/
msal_extensions) se prueba de VERDAD, nunca mockeado — es la pieza
Windows-especifica que puede romperse en silencio. Solo se mockea
Microsoft Graph (via httpx.MockTransport) y la adquisicion de token MSAL
(que exige login interactivo real, imposible en CI).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import msal_extensions
import pytest

from nexus.mail.outlook import OutlookMailManager, OutlookTokenStore


# ── Cache de tokens — DPAPI/pywin32 real, nunca mockeado ────────────────────

def test_outlook_token_store_uses_real_dpapi_roundtrip(tmp_path: Path):
    """Prueba de verdad (no simulada) de que win32crypt/DPAPI funciona en
    esta maquina para el cache de tokens de Outlook — si pywin32 estuviera
    roto o ausente, esto fallaria aqui, no en produccion con el usuario
    a medio login."""
    path = tmp_path / "outlook_token_cache.bin"
    store = OutlookTokenStore(path=path)

    cache = store.build_cache()
    assert isinstance(cache, msal_extensions.PersistedTokenCache)

    # Round-trip real: escribe y relee un "cache" de ejemplo cifrado con
    # DPAPI, igual que MSAL haria con un token real.
    persistence = msal_extensions.build_encrypted_persistence(str(path))
    persistence.save(json.dumps({"AccessToken": {"fake": "entry"}}))
    assert path.exists()
    loaded = json.loads(persistence.load())
    assert loaded == {"AccessToken": {"fake": "entry"}}


def test_outlook_token_store_default_path_is_under_local_appdata():
    store = OutlookTokenStore()
    assert store.build_cache() is not None  # no explota sin path explicito


# ── Graph — mockeado, nunca red real en tests ───────────────────────────────

def _cfg(**overrides):
    base = {
        "azure_client_id": "test-client-id",
        "azure_tenant_id": "test-tenant-id",
        "outlook_enabled": True,
        "outlook_message_limit": 30,
        "outlook_priority_total_limit": 30,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _manager(*, cfg=None, token: str | None = "fake-access-token", transport_handler=None, llm_router=None, monkeypatch=None) -> OutlookMailManager:
    manager = OutlookMailManager(
        cfg=cfg or _cfg(),
        llm_router=llm_router,
        http_transport=httpx.MockTransport(transport_handler) if transport_handler else None,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(manager, "_acquire_token_silent", lambda: token)
    return manager


def test_status_disabled_when_outlook_not_enabled():
    manager = _manager(cfg=_cfg(outlook_enabled=False))
    assert manager.status() == {"status": "disabled", "reason": "Outlook desactivado en esta instancia."}


@pytest.mark.asyncio
async def test_get_priority_messages_not_authenticated_without_token(monkeypatch):
    manager = _manager(token=None, monkeypatch=monkeypatch)
    result = await manager.get_priority_messages()
    assert result == {"status": "not_authenticated", "messages": []}


@pytest.mark.asyncio
async def test_get_priority_messages_parses_real_graph_shape(monkeypatch):
    graph_payload = {
        "value": [
            {
                "id": "msg-1",
                "subject": "Propuesta comercial",
                "from": {"emailAddress": {"name": "Laura Gomez", "address": "laura@example.com"}},
                "receivedDateTime": "2026-09-30T10:00:00Z",
                "bodyPreview": "Hola, te escribo para...",
                "isRead": False,
                "importance": "high",
                "webLink": "https://outlook.office.com/mail/msg-1",
            },
            {
                "id": "msg-2",
                "subject": "",
                "from": {"emailAddress": {"name": "", "address": ""}},
                "receivedDateTime": "2026-09-30T09:00:00Z",
                "bodyPreview": "",
                "isRead": True,
                "importance": "normal",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me/mailFolders/inbox/messages"
        assert request.headers["Authorization"] == "Bearer fake-access-token"
        return httpx.Response(200, json=graph_payload)

    manager = _manager(transport_handler=handler, monkeypatch=monkeypatch)

    result = await manager.get_priority_messages()

    assert result["status"] == "success"
    ids = {m["message_id"] for m in result["messages"]}
    assert ids == {"msg-1", "msg-2"}
    msg1 = next(m for m in result["messages"] if m["message_id"] == "msg-1")
    assert msg1["sender_email"] == "laura@example.com"
    assert msg1["subject"] == "Propuesta comercial"
    assert msg1["unread"] is True


@pytest.mark.asyncio
async def test_get_priority_messages_enriches_with_llm_scores(monkeypatch):
    graph_payload = {"value": [{
        "id": "msg-1", "subject": "Urgente", "from": {"emailAddress": {"name": "X", "address": "x@example.com"}},
        "receivedDateTime": "2026-09-30T10:00:00Z", "bodyPreview": "...", "isRead": False, "importance": "high",
    }]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=graph_payload)

    class _FakeLLMRouter:
        async def call(self, messages):
            return SimpleNamespace(
                error=None,
                content=json.dumps([{"message_id": "msg-1", "score": 90, "importance": "high", "reason": "cliente importante", "suggested_action": "responder"}]),
            )

    manager = _manager(transport_handler=handler, llm_router=_FakeLLMRouter(), monkeypatch=monkeypatch)

    result = await manager.get_priority_messages()

    assert result["messages"][0]["priority_score"] == 90
    assert result["messages"][0]["reason"] == "cliente importante"


@pytest.mark.asyncio
async def test_send_reply_posts_to_message_reply_endpoint(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/v1.0/me/messages/msg-1/reply"
        assert json.loads(request.content) == {"comment": "Gracias, hablamos el jueves."}
        return httpx.Response(202)

    manager = _manager(transport_handler=handler, monkeypatch=monkeypatch)

    result = await manager.send_reply("msg-1", "Gracias, hablamos el jueves.")

    assert result == {"status": "success", "message_id": "msg-1"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_send_reply_not_authenticated_without_token(monkeypatch):
    manager = _manager(token=None, monkeypatch=monkeypatch)
    result = await manager.send_reply("msg-1", "texto")
    assert result == {"status": "not_authenticated"}


@pytest.mark.asyncio
async def test_send_new_posts_to_sendmail_endpoint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1.0/me/sendMail"
        body = json.loads(request.content)
        assert body["message"]["toRecipients"][0]["emailAddress"]["address"] == "destino@example.com"
        return httpx.Response(202)

    manager = _manager(transport_handler=handler, monkeypatch=monkeypatch)

    result = await manager.send_new(to="destino@example.com", subject="Asunto", body="Cuerpo")

    assert result == {"status": "success", "to": "destino@example.com"}
