"""tests/unit/test_coordinator_stale_pending.py

Bug real visto en vivo: tras proponer un cambio de velocidad del raton, el
siguiente mensaje (una pregunta de Cisco) recibia "¿Confirmas el cambio...?"
en bucle hasta decir si/no. Las propuestas de si/no puro (raton, ticket) ahora
caducan si el usuario contesta con otra cosa: se descartan (no se ejecuta
nada) y el mensaje se procesa normal.
"""

from __future__ import annotations

import pytest

from nexus.api.schemas.chat import ChatRequest
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


class _PendingAgent:
    def __init__(self) -> None:
        self.pending = True
        self.cancelled = 0
        self.confirmed = 0

    def has_pending(self, context_id: str) -> bool:
        return self.pending

    def cancel(self, context_id: str) -> None:
        self.pending = False
        self.cancelled += 1

    def confirm(self, context_id: str, *a, **k):
        self.pending = False
        self.confirmed += 1
        return {"previous": 6, "applied": 3}


def _coordinator(**agents) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None, grafana=None, prometheus=None,
        incident_repository=MemoryIncidentRepository(), audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(), **agents,
    )


@pytest.mark.asyncio
async def test_unrelated_message_drops_the_mouse_proposal_and_is_handled_normally():
    mouse = _PendingAgent()
    coordinator = _coordinator(mouse_agent=mouse)

    response = await coordinator.handle_chat(
        ChatRequest(message="que switches y routers cisco la soportan?"),
        resolution_override={"skill_id": "general.respuesta", "entities": {}},
    )

    assert mouse.cancelled == 1 and mouse.confirmed == 0
    assert "Confirmas" not in response.response
    assert response.agent != "desktop-mouse-agent"


@pytest.mark.asyncio
async def test_yes_still_confirms_the_mouse_proposal():
    mouse = _PendingAgent()
    coordinator = _coordinator(mouse_agent=mouse)

    response = await coordinator.handle_chat(ChatRequest(message="sí"))

    assert mouse.confirmed == 1 and mouse.cancelled == 0
    assert "cambiada de 6 a 3" in response.response


@pytest.mark.asyncio
async def test_no_cancels_the_mouse_proposal():
    mouse = _PendingAgent()
    coordinator = _coordinator(mouse_agent=mouse)

    response = await coordinator.handle_chat(ChatRequest(message="no"))

    assert mouse.cancelled == 1 and mouse.confirmed == 0
    assert "no toco nada" in response.response
