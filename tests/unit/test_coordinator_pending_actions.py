"""tests/unit/test_coordinator_pending_actions.py

Tests unitarios para la unificacion de la cola de revision de Campaña con
el resto de acciones pendientes de PEPO (Mouse/SystemTask/RemoteOps/
SelfConfig) en NexusCoordinator — list_pending_actions() ahora es async y
agrega tambien CampaignAgent.list_pending(); confirm/cancel enrutan por el
prefijo "campaign:" a send_to_prospect/discard_prospect en vez del bucle
has_pending() (que Campaña no implementa).
"""

from __future__ import annotations

import pytest

from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


class _FakeChatAgent:
    """Forma minima de Mouse/SystemTask/RemoteOps/SelfConfig — un pendiente
    por context_id, confirm/cancel sincronos por simplicidad (algunos reales
    son async; el coordinador ya los await donde toca, cubierto por los
    tests existentes de cada agente)."""

    def __init__(self, agent_id: str, *, pending_context_id: str | None = None):
        self.agent_id = agent_id
        self._pending_context_id = pending_context_id
        self.confirm_calls: list[tuple] = []
        self.cancel_calls: list[str] = []

    async def list_pending(self) -> list[dict]:
        if self._pending_context_id is None:
            return []
        return [{
            "context_id": self._pending_context_id,
            "agent_id": self.agent_id,
            "kind": "task",
            "summary": "algo pendiente",
        }]

    def has_pending(self, context_id: str) -> bool:
        return context_id == self._pending_context_id

    async def confirm(self, context_id: str, user_reply: str | None = None):
        self.confirm_calls.append((context_id, user_reply))
        return {"done": True}

    def cancel(self, context_id: str) -> None:
        self.cancel_calls.append(context_id)
        self._pending_context_id = None


class _FakeCampaignAgent:
    def __init__(self, *, pending: list[dict] | None = None):
        self._pending = pending or []
        self.send_calls: list[str] = []
        self.discard_calls: list[str] = []

    async def list_pending(self) -> list[dict]:
        return [
            {
                "context_id": f"campaign:{r['result_id']}",
                "agent_id": "campaign",
                "kind": "review",
                "summary": f"{r['name']} — oportunidad {r['opportunity_score']}",
            }
            for r in self._pending
        ]

    async def send_to_prospect(self, result_id: str) -> dict:
        self.send_calls.append(result_id)
        if not any(r["result_id"] == result_id for r in self._pending):
            return {"status": "not_found", "result_id": result_id}
        return {"status": "sent", "result_id": result_id}

    async def discard_prospect(self, result_id: str) -> dict:
        self.discard_calls.append(result_id)
        if not any(r["result_id"] == result_id for r in self._pending):
            return {"status": "not_found", "result_id": result_id}
        return {"status": "ok", "result_id": result_id}


def _coordinator(*, self_config_agent=None, campaign_agent=None) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None,
        grafana=None,
        prometheus=None,
        incident_repository=MemoryIncidentRepository(),
        audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(),
        self_config_agent=self_config_agent,
        campaign_agent=campaign_agent,
    )


@pytest.mark.asyncio
async def test_list_pending_actions_aggregates_campaign_alongside_chat_agents():
    self_config = _FakeChatAgent("self_config", pending_context_id="ctx-1")
    campaign = _FakeCampaignAgent(pending=[
        {"result_id": "r1", "name": "Panaderia Ana", "opportunity_score": 62},
        {"result_id": "r2", "name": "Taller Luis", "opportunity_score": 58},
    ])
    coordinator = _coordinator(self_config_agent=self_config, campaign_agent=campaign)

    pending = await coordinator.list_pending_actions()

    context_ids = {item["context_id"] for item in pending}
    assert context_ids == {"ctx-1", "campaign:r1", "campaign:r2"}
    assert all(item["agent_id"] in {"self_config", "campaign"} for item in pending)


@pytest.mark.asyncio
async def test_confirm_pending_action_routes_campaign_prefix_to_send_to_prospect():
    campaign = _FakeCampaignAgent(pending=[
        {"result_id": "r1", "name": "Panaderia Ana", "opportunity_score": 62},
    ])
    coordinator = _coordinator(campaign_agent=campaign)

    result = await coordinator.confirm_pending_action("campaign:r1")

    assert result["status"] == "ok"
    assert campaign.send_calls == ["r1"]


@pytest.mark.asyncio
async def test_cancel_pending_action_routes_campaign_prefix_to_discard_prospect():
    campaign = _FakeCampaignAgent(pending=[
        {"result_id": "r1", "name": "Panaderia Ana", "opportunity_score": 62},
    ])
    coordinator = _coordinator(campaign_agent=campaign)

    result = await coordinator.cancel_pending_action("campaign:r1")

    assert result["status"] == "ok"
    assert campaign.discard_calls == ["r1"]


@pytest.mark.asyncio
async def test_confirm_pending_action_campaign_not_found():
    campaign = _FakeCampaignAgent(pending=[])
    coordinator = _coordinator(campaign_agent=campaign)

    result = await coordinator.confirm_pending_action("campaign:no-existe")

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_confirm_pending_action_campaign_prefix_without_campaign_agent_configured():
    coordinator = _coordinator(campaign_agent=None)

    result = await coordinator.confirm_pending_action("campaign:r1")

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_confirm_pending_action_still_routes_normal_context_id_to_chat_agent():
    """El prefijo 'campaign:' no debe interferir con el enrutado normal por
    has_pending() de los otros agentes — regresion del comportamiento
    existente."""
    self_config = _FakeChatAgent("self_config", pending_context_id="ctx-1")
    coordinator = _coordinator(self_config_agent=self_config)

    result = await coordinator.confirm_pending_action("ctx-1", "sí")

    assert result["status"] == "ok"
    assert self_config.confirm_calls == [("ctx-1", "sí")]
