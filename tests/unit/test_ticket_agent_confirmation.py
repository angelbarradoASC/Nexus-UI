"""tests/unit/test_ticket_agent_confirmation.py

Regresion: PEPO creaba un ticket real en Assets en cuanto el clasificador de
intencion resolvia assets.crear_ticket_operador, sin pedir confirmacion —
una pregunta meta ("por que da timeout?") se clasifico asi y creo un ticket
que nadie pidio. La clasificacion de intencion nunca va a ser perfecta; el
freno real tiene que ser la confirmacion humana antes de escribir en un
sistema externo, igual que ya exige mouse_speed/system_task. Estos tests
cubren tanto TicketAgent en aislado como el flujo completo via
NexusCoordinator.handle_chat().
"""

from __future__ import annotations

import pytest

from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.operations.ticket_agent import TicketAgent
from nexus.orchestration.coordinator import NexusCoordinator
from nexus.api.schemas.chat import ChatRequest


class _FakeOperations:
    def __init__(self):
        self.enrich_calls: list[str] = []
        self.create_calls: list[dict] = []

    async def enrich_ticket_from_message(self, message, *, source, trigger_kind, context):
        self.enrich_calls.append(message)
        return {
            "status": "ok",
            "ticket_payload": {
                "title": "Investigar timeout no especificado",
                "ticket_type": "bug",
                "priority": "medium",
                "status": "pending",
                "description": message,
            },
            "extracted": {},
        }

    async def create_ticket(self, payload):
        self.create_calls.append(payload)
        return {"task": {"id": 11, "title": payload["title"]}}


# ── TicketAgent en aislado ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_only_enriches_never_creates():
    ops = _FakeOperations()
    agent = TicketAgent(ops)

    proposal = await agent.propose("ctx-1", "por que da timeout?", actor="angel", context={})

    assert ops.enrich_calls == ["por que da timeout?"]
    assert ops.create_calls == []
    assert agent.has_pending("ctx-1") is True
    assert proposal["ticket_payload"]["title"] == "Investigar timeout no especificado"


@pytest.mark.asyncio
async def test_confirm_creates_the_previously_proposed_payload():
    ops = _FakeOperations()
    agent = TicketAgent(ops)
    await agent.propose("ctx-1", "por que da timeout?", actor="angel", context={})

    result = await agent.confirm("ctx-1")

    assert len(ops.create_calls) == 1
    assert ops.create_calls[0]["title"] == "Investigar timeout no especificado"
    assert result["task_id"] == 11
    assert agent.has_pending("ctx-1") is False


@pytest.mark.asyncio
async def test_cancel_discards_proposal_without_creating():
    ops = _FakeOperations()
    agent = TicketAgent(ops)
    await agent.propose("ctx-1", "por que da timeout?", actor="angel", context={})

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert ops.create_calls == []


@pytest.mark.asyncio
async def test_confirm_without_pending_returns_none():
    agent = TicketAgent(_FakeOperations())

    assert await agent.confirm("nunca-propuesto") is None


# ── Flujo completo via NexusCoordinator.handle_chat() ───────────────────────


def _coordinator(ops: _FakeOperations) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None,
        grafana=None,
        prometheus=None,
        incident_repository=MemoryIncidentRepository(),
        audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(),
        ticket_agent=TicketAgent(ops),
    )


@pytest.mark.asyncio
async def test_chat_never_creates_a_ticket_before_confirmation():
    ops = _FakeOperations()
    coordinator = _coordinator(ops)
    payload = ChatRequest(message="por que da timeout?", user_id="angel", context_id="ctx-1")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "assets.crear_ticket_operador", "entities": {}}
    )

    assert ops.create_calls == []
    assert "confirmas" in response.response.lower()


@pytest.mark.asyncio
async def test_chat_creates_the_ticket_only_after_explicit_yes():
    ops = _FakeOperations()
    coordinator = _coordinator(ops)
    propose_payload = ChatRequest(message="por que da timeout?", user_id="angel", context_id="ctx-1")
    await coordinator.handle_chat(
        propose_payload, resolution_override={"skill_id": "assets.crear_ticket_operador", "entities": {}}
    )

    confirm_payload = ChatRequest(message="si", user_id="angel", context_id="ctx-1")
    response = await coordinator.handle_chat(confirm_payload)

    assert len(ops.create_calls) == 1
    assert "#11" in response.response


@pytest.mark.asyncio
async def test_chat_saying_no_cancels_without_creating():
    ops = _FakeOperations()
    coordinator = _coordinator(ops)
    propose_payload = ChatRequest(message="por que da timeout?", user_id="angel", context_id="ctx-1")
    await coordinator.handle_chat(
        propose_payload, resolution_override={"skill_id": "assets.crear_ticket_operador", "entities": {}}
    )

    confirm_payload = ChatRequest(message="no", user_id="angel", context_id="ctx-1")
    response = await coordinator.handle_chat(confirm_payload)

    assert ops.create_calls == []
    assert "no creo el ticket" in response.response.lower()
