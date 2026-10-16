"""tests/unit/test_coordinator_outlook_priority.py

PEPO respondiendo "tengo algún correo de hoy?" (skill mail.outlook_priority)
— bug real visto en vivo: antes mezclaba newsletters/spam con correos
reales sin filtrar, y si la puntuación LLM fallaba (pasó dos veces en
vivo: HTTP 413 y 429 reales de Groq) volcaba el bodyPreview en crudo,
ilegible (HTML mal convertido, saltos de línea sueltos). Ahora solo
muestra lo puntuado como high/medium, y nunca cae al preview en bruto.
"""

from __future__ import annotations

import pytest

from nexus.api.schemas.chat import ChatRequest
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


class _FakeOutlook:
    def __init__(self, result: dict) -> None:
        self._result = result

    async def get_priority_messages(self, limit=None) -> dict:
        return self._result


def _coordinator(*, outlook=None) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None,
        grafana=None,
        prometheus=None,
        incident_repository=MemoryIncidentRepository(),
        audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(),
        outlook=outlook,
    )


def _msg(**overrides) -> dict:
    base = {
        "message_id": "msg-1",
        "sender_name": "Laura",
        "sender_email": "laura@example.com",
        "subject": "Propuesta",
        "preview": "texto del correo",
        "importance": "low",
        "reason": "",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_only_high_and_medium_importance_messages_are_shown():
    outlook = _FakeOutlook({
        "status": "success",
        "messages": [
            _msg(message_id="m1", sender_name="Instagram", subject="Nuevos seguidores", importance="low"),
            _msg(message_id="m2", sender_name="Laura", subject="Propuesta comercial", importance="high", reason="cliente importante"),
        ],
    })
    coordinator = _coordinator(outlook=outlook)
    payload = ChatRequest(message="tengo algun correo de hoy?")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "mail.outlook_priority", "entities": {}}
    )

    assert "Laura" in response.response
    assert "Propuesta comercial" in response.response
    assert "Instagram" not in response.response
    assert "Nuevos seguidores" not in response.response


@pytest.mark.asyncio
async def test_never_falls_back_to_raw_preview_text():
    """Antes, sin 'reason' (ej. la puntuacion LLM fallo), se mostraba el
    bodyPreview en crudo — ilegible para correos HTML. Ahora, sin reason,
    solo se muestra remitente+asunto."""
    outlook = _FakeOutlook({
        "status": "success",
        "messages": [
            _msg(message_id="m1", sender_name="Cliente", subject="Oferta", importance="high",
                 reason="", preview="根据你的兴趣推荐的账户 打开 Instagram 为你推荐 texto roto sin sentido"),
        ],
    })
    coordinator = _coordinator(outlook=outlook)
    payload = ChatRequest(message="tengo algun correo de hoy?")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "mail.outlook_priority", "entities": {}}
    )

    assert "Cliente" in response.response
    assert "Oferta" in response.response
    assert "Instagram" not in response.response
    assert "texto roto" not in response.response


@pytest.mark.asyncio
async def test_honest_when_nothing_important_instead_of_showing_low_priority():
    outlook = _FakeOutlook({
        "status": "success",
        "messages": [_msg(message_id="m1", importance="low"), _msg(message_id="m2", importance="low")],
    })
    coordinator = _coordinator(outlook=outlook)
    payload = ChatRequest(message="tengo algun correo de hoy?")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "mail.outlook_priority", "entities": {}}
    )

    assert "no veo nada" in response.response.lower() or "no destaque" in response.response.lower()


@pytest.mark.asyncio
async def test_not_authenticated_gives_clear_instruction():
    outlook = _FakeOutlook({"status": "not_authenticated", "messages": []})
    coordinator = _coordinator(outlook=outlook)
    payload = ChatRequest(message="tengo algun correo de hoy?")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "mail.outlook_priority", "entities": {}}
    )

    assert "Configuración" in response.response


@pytest.mark.asyncio
async def test_unscored_messages_are_not_reported_as_nothing_important():
    """Bug real (cuota de Groq agotada el 2026-10-01): todos los correos
    quedaban en importance='low' por defecto y PEPO decia 'no hay nada
    importante' — una mentira, en realidad no habia podido puntuar nada."""
    outlook = _FakeOutlook({
        "status": "success",
        "messages": [_msg(message_id="m1", importance="low"), _msg(message_id="m2", importance="low")],
        "scoring": {"scored": 0, "unscored": 2, "degraded": True},
    })
    coordinator = _coordinator(outlook=outlook)

    response = await coordinator.handle_chat(
        ChatRequest(message="tengo algun correo de hoy?"),
        resolution_override={"skill_id": "mail.outlook_priority", "entities": {}},
    )

    assert "no puedo decirte" in response.response.lower()
    assert "2 correos" in response.response
    assert "no veo nada" not in response.response.lower()


@pytest.mark.asyncio
async def test_partial_scoring_shows_important_ones_and_warns_about_the_rest():
    outlook = _FakeOutlook({
        "status": "success",
        "messages": [
            _msg(message_id="m1", sender_name="Laura", subject="Propuesta", importance="high", reason="cliente"),
            _msg(message_id="m2", importance="low"),
        ],
        "scoring": {"scored": 1, "unscored": 1, "degraded": True},
    })
    coordinator = _coordinator(outlook=outlook)

    response = await coordinator.handle_chat(
        ChatRequest(message="tengo algun correo de hoy?"),
        resolution_override={"skill_id": "mail.outlook_priority", "entities": {}},
    )

    assert "Laura" in response.response
    assert "1 correo todavía sin puntuar" in response.response
