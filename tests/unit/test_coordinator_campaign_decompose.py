"""tests/unit/test_coordinator_campaign_decompose.py

Tests unitarios para el enrutado de PEPO hacia CampaignDecomposer —
skill campaign.qualify, de solo lectura (no ConfirmableAgent, no hay nada
que confirmar). Comparte la misma función que el cuadro de la pantalla de
Campaña, pedido así explícitamente por el usuario.
"""

from __future__ import annotations

import pytest

from nexus.api.schemas.chat import ChatRequest
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


class _FakeCampaignDecomposer:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.calls: list[str] = []

    async def decompose_and_verify(self, text: str) -> dict:
        self.calls.append(text)
        return self._result


def _coordinator(*, campaign_decomposer=None) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None,
        grafana=None,
        prometheus=None,
        incident_repository=MemoryIncidentRepository(),
        audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(),
        campaign_decomposer=campaign_decomposer,
    )


@pytest.mark.asyncio
async def test_consistent_result_mentions_similarity_percentage():
    decomposer = _FakeCampaignDecomposer({
        "status": "ok",
        "query": {"business_type": "peluquerías", "city": "Zaragoza", "radius_km": 12},
        "reconstructed": "peluquerías en Zaragoza en un radio de 12 km",
        "similarity": 1.0,
        "consistent": True,
        "note": "El LLM entendió lo mismo que pediste.",
    })
    coordinator = _coordinator(campaign_decomposer=decomposer)
    payload = ChatRequest(message="cualificar peluquerías en Zaragoza a 12km")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "campaign.qualify", "entities": {}}
    )

    assert response.status == "accepted"
    assert response.agent == "campaign-decomposer"
    assert "peluquerías en Zaragoza" in response.response
    assert "100%" in response.response
    assert decomposer.calls == ["cualificar peluquerías en Zaragoza a 12km"]


@pytest.mark.asyncio
async def test_inconsistent_result_flags_deviation():
    decomposer = _FakeCampaignDecomposer({
        "status": "ok",
        "query": {"business_type": "peluquerías", "city": "Zaragoza", "radius_km": None},
        "reconstructed": "restaurantes en Madrid",
        "similarity": 0.2,
        "consistent": False,
        "note": "El LLM se desvió al descomponer — revisa antes de seguir.",
    })
    coordinator = _coordinator(campaign_decomposer=decomposer)
    payload = ChatRequest(message="cualificar peluquerías en Zaragoza")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "campaign.qualify", "entities": {}}
    )

    assert "Ojo" in response.response
    assert "20%" in response.response


@pytest.mark.asyncio
async def test_unverified_result_shows_note_instead_of_percentage():
    decomposer = _FakeCampaignDecomposer({
        "status": "ok",
        "query": {"business_type": "peluquerías", "city": "Zaragoza", "radius_km": None},
        "reconstructed": None,
        "similarity": None,
        "consistent": None,
        "note": "El LLM local no respondió — descomposición sin comprobar.",
    })
    coordinator = _coordinator(campaign_decomposer=decomposer)
    payload = ChatRequest(message="cualificar peluquerías en Zaragoza")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "campaign.qualify", "entities": {}}
    )

    assert "no respondió" in response.response


@pytest.mark.asyncio
async def test_error_status_is_reported_as_degraded():
    decomposer = _FakeCampaignDecomposer({"status": "error", "error": "texto vacío"})
    coordinator = _coordinator(campaign_decomposer=decomposer)
    payload = ChatRequest(message="cualificar")

    response = await coordinator.handle_chat(
        payload, resolution_override={"skill_id": "campaign.qualify", "entities": {}}
    )

    assert response.status == "degraded"
    assert "No he podido descomponerlo" in response.response
