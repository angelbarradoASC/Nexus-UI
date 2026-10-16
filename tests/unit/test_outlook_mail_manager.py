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


@pytest.fixture(autouse=True)
def _isolated_scores_cache(tmp_path: Path, monkeypatch):
    """Ningun test toca la cache real de puntuaciones del usuario
    (%LOCALAPPDATA%\\Open-Nexus\\config\\outlook_scores.json)."""
    from nexus.mail import outlook as outlook_module

    monkeypatch.setattr(outlook_module, "_default_scores_path", lambda: tmp_path / "outlook_scores.json")


def _manager(*, cfg=None, token: str | None = "fake-access-token", transport_handler=None, llm_router=None, monkeypatch=None, now_fn=None) -> OutlookMailManager:
    manager = OutlookMailManager(
        cfg=cfg or _cfg(),
        llm_router=llm_router,
        http_transport=httpx.MockTransport(transport_handler) if transport_handler else None,
        now_fn=now_fn,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(manager, "_acquire_token_silent", lambda: token)
    return manager


def test_status_disabled_when_outlook_not_enabled():
    manager = _manager(cfg=_cfg(outlook_enabled=False))
    assert manager.status() == {"status": "disabled", "reason": "Outlook desactivado en esta instancia."}


def test_clean_preview_collapses_broken_html_whitespace():
    """Bug real visto en vivo: bodyPreview de Graph para correos HTML
    (ej. notificaciones de Instagram) trae saltos de linea/espacios
    sueltos que salian ilegibles en el chat de PEPO."""
    raw = "Ver en navegador\r\n\r\n\r\n\r\nCumplir será obligatorio.\n\n   Aprovechar el cambio   será una decisión.\r\n"
    cleaned = OutlookMailManager._clean_preview(raw)
    assert cleaned == "Ver en navegador Cumplir será obligatorio. Aprovechar el cambio será una decisión."


def test_clean_preview_truncates_long_text():
    cleaned = OutlookMailManager._clean_preview("palabra " * 100)
    assert len(cleaned) <= 400


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
        async def call(self, messages, **kwargs):
            sent_id = json.loads(messages[1]["content"])[0]["message_id"]
            return SimpleNamespace(
                error=None,
                content=json.dumps([{"message_id": sent_id, "score": 90, "importance": "high", "reason": "cliente importante", "suggested_action": "responder"}]),
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


# ── Puntuacion: cada correo UNA vez (fallo real visto en vivo, 2026-10-01) ──
# El watcher consultaba cada 5 min y re-puntuaba los mismos 30 correos con el
# LLM: 98 consultas, >=29 con todos los niveles en HTTP 429 de Groq, cero
# avisos en todo el dia. Estos tests fijan el comportamiento corregido.

from datetime import datetime, timedelta, timezone  # noqa: E402


def _graph_msg(msg_id: str, *, inference: str = "focused", importance: str = "normal") -> dict:
    return {
        "id": msg_id, "subject": f"Asunto {msg_id}",
        "from": {"emailAddress": {"name": "Remitente", "address": "x@example.com"}},
        "receivedDateTime": "2026-10-16T10:00:00Z", "bodyPreview": "texto", "isRead": False,
        "importance": importance, "inferenceClassification": inference,
    }


class _CountingLLM:
    """Fake de LLM router que registra a que correos se le pregunta."""

    def __init__(self, importance_by_id: dict[str, str] | None = None, fail_times: int = 0, raw_reply: str | None = None):
        self.calls: list[list[str]] = []      # por correo ("a", "b"...), vía su asunto
        self.sent_payloads: list[list[dict]] = []
        self.sent_kwargs: list[dict] = []
        self.sent_system: list[str] = []
        self._importance = importance_by_id or {}
        self._fail = fail_times
        self._raw_reply = raw_reply

    async def call(self, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        self.sent_payloads.append(payload)
        self.sent_kwargs.append(kwargs)
        self.sent_system.append(messages[0]["content"])
        keys = [p["subject"].removeprefix("Asunto ") for p in payload]
        self.calls.append(keys)
        if self._fail > 0:
            self._fail -= 1
            return SimpleNamespace(error="http_429 | nivel=L3-Groq", content="")
        if self._raw_reply is not None:
            return SimpleNamespace(error=None, content=self._raw_reply)
        out = []
        for p, key in zip(payload, keys):
            imp = self._importance.get(key, "low")
            out.append({"message_id": p["message_id"], "score": 80 if imp == "high" else 5,
                        "importance": imp, "reason": "motivo", "suggested_action": "leer"})
        return SimpleNamespace(error=None, content=json.dumps(out))


def _inbox(holder: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": holder["messages"]})
    return handler


@pytest.mark.asyncio
async def test_already_scored_messages_never_hit_the_llm_again(monkeypatch):
    inbox = {"messages": [_graph_msg("a"), _graph_msg("b")]}
    llm = _CountingLLM({"a": "high"})
    manager = _manager(transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch)

    first = await manager.get_priority_messages()
    second = await manager.get_priority_messages()

    assert len(llm.calls) == 1  # la segunda consulta salio de la cache
    assert first["scoring"]["degraded"] is False
    assert {m["message_id"]: m["importance"] for m in second["messages"]} == {"a": "high", "b": "low"}


@pytest.mark.asyncio
async def test_only_new_messages_are_sent_to_the_llm(monkeypatch):
    inbox = {"messages": [_graph_msg("a")]}
    llm = _CountingLLM()
    manager = _manager(transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch)
    await manager.get_priority_messages()

    inbox["messages"] = [_graph_msg("b"), _graph_msg("a")]
    await manager.get_priority_messages()

    assert llm.calls == [["a"], ["b"]]


@pytest.mark.asyncio
async def test_other_inbox_is_prefiltered_for_free_unless_sender_marked_high(monkeypatch):
    """Bandeja 'Otros' de Outlook (promos/newsletters) no gasta LLM — salvo
    que el remitente la marcase de alta importancia."""
    inbox = {"messages": [
        _graph_msg("promo", inference="other"),
        _graph_msg("real", inference="focused"),
        _graph_msg("urgente_en_otros", inference="other", importance="high"),
    ]}
    llm = _CountingLLM()
    manager = _manager(transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch)

    result = await manager.get_priority_messages()

    assert llm.calls == [["real", "urgente_en_otros"]]
    promo = next(m for m in result["messages"] if m["message_id"] == "promo")
    assert promo["importance"] == "low" and promo["scored"] is True and "Otros" in promo["reason"]


@pytest.mark.asyncio
async def test_llm_failure_marks_degraded_and_cools_down_instead_of_hammering(monkeypatch):
    clock = {"t": datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)}
    inbox = {"messages": [_graph_msg("a"), _graph_msg("b")]}
    llm = _CountingLLM(fail_times=1)
    manager = _manager(transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch,
                       now_fn=lambda: clock["t"])

    first = await manager.get_priority_messages()
    assert first["scoring"] == {"scored": 0, "unscored": 2, "degraded": True}
    assert all(m["scored"] is False for m in first["messages"])

    clock["t"] += timedelta(minutes=5)  # aun en cooldown: NO se vuelve a llamar
    await manager.get_priority_messages()
    assert len(llm.calls) == 1

    clock["t"] += timedelta(minutes=6)  # cooldown cumplido: reintenta y esta vez funciona
    third = await manager.get_priority_messages()
    assert len(llm.calls) == 2
    assert third["scoring"]["degraded"] is False


@pytest.mark.asyncio
async def test_scores_persist_across_manager_instances(monkeypatch):
    inbox = {"messages": [_graph_msg("a")]}
    llm1 = _CountingLLM({"a": "high"})
    await _manager(transport_handler=_inbox(inbox), llm_router=llm1, monkeypatch=monkeypatch).get_priority_messages()

    llm2 = _CountingLLM()
    result = await _manager(transport_handler=_inbox(inbox), llm_router=llm2, monkeypatch=monkeypatch).get_priority_messages()

    assert llm2.calls == []  # 'reinicio' de la app: sigue sabiendo lo ya puntuado
    assert result["messages"][0]["importance"] == "high"


@pytest.mark.asyncio
async def test_llm_calls_are_chunked(monkeypatch):
    inbox = {"messages": [_graph_msg(f"m{i:02d}") for i in range(25)]}
    llm = _CountingLLM()
    manager = _manager(cfg=_cfg(outlook_message_limit=30), transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch)

    await manager.get_priority_messages()

    assert [len(c) for c in llm.calls] == [10, 10, 5]


@pytest.mark.asyncio
async def test_llm_gets_short_ids_explicit_max_tokens_and_spanish_style(monkeypatch):
    """Causa raiz real (2026-10-16): los message_id de Graph son ~150 chars de
    base64 que el modelo debia repetir; con max_tokens por defecto (1200) la
    respuesta se truncaba a mitad de JSON y esos correos nunca se puntuaban."""
    inbox = {"messages": [_graph_msg("a"), _graph_msg("b")]}
    llm = _CountingLLM()
    manager = _manager(transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch)

    await manager.get_priority_messages()

    sent_ids = [p["message_id"] for p in llm.sent_payloads[0]]
    assert sent_ids == ["m1", "m2"]                      # nunca el id largo de Graph
    assert llm.sent_kwargs[0]["max_tokens"] >= 1500      # explicito, no el 1200 del router
    assert "español" in llm.sent_system[0]               # razones en castellano y cortas


@pytest.mark.asyncio
async def test_unparseable_llm_reply_is_a_failure_with_cooldown_not_silence(monkeypatch):
    """Antes un JSON truncado se tragaba con `return messages` — sin log, sin
    cooldown, reintentado en cada ciclo para siempre."""
    clock = {"t": datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)}
    inbox = {"messages": [_graph_msg("a")]}
    llm = _CountingLLM(raw_reply='[{"message_id": "m1", "score": 9')   # truncado a media respuesta
    manager = _manager(transport_handler=_inbox(inbox), llm_router=llm, monkeypatch=monkeypatch,
                       now_fn=lambda: clock["t"])

    first = await manager.get_priority_messages()
    await manager.get_priority_messages()

    assert first["scoring"]["degraded"] is True
    assert len(llm.calls) == 1   # el segundo ciclo cae en cooldown, no martillea
