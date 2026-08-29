"""tests/unit/test_prospecting_brave_budget.py

Tests de integración ligera: el presupuesto mensual de Brave (BraveApiBudget)
se respeta de verdad en los dos puntos donde ProspectingAgentService llama a
Brave — el bucle de discovery (_discover_with_brave, una llamada por query) y
el enriquecimiento por candidato (_enrich_candidate_with_brave, una llamada
por candidato) — que antes no tenian ningun tope de volumen mensual.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus.prospecting.models import ProspectingBrief
from nexus.prospecting.repository import ProspectingRepository
from nexus.prospecting.service import ProspectingAgentService


class _FakeConnector:
    configured = True

    async def find_company_by_domain(self, domain: str):
        return None

    async def find_company_by_email(self, email: str):
        return None

    async def find_company_by_name(self, name: str):
        return None

    async def list_pipeline(self):
        return {"companies": []}


class _FakeBrave:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search(self, *, run_id: str, query: str, country: str = "es", language: str = "es", count: int = 10, offset: int = 0):
        self.calls.append(query)
        return {"provider": "brave", "query": query, "results": []}


@pytest.fixture
def cfg(tmp_path):
    return SimpleNamespace(
        prospecting_data_dir=str(tmp_path / "prospecting"),
        assets_crm_base_url="http://127.0.0.1:8000",
        assets_crm_username="",
        assets_crm_password="",
        prospecting_http_timeout_seconds=5,
        prospecting_user_agent="test-agent",
        prospecting_max_pages_per_site=3,
        local_llm_enabled=False,
        local_llm_base_url=None,
        local_llm_model="",
        local_llm_provider="openai_compatible",
        local_llm_timeout=10,
        local_llm_retries=1,
        local_llm_api_key="not-needed",
        brave_search_enabled=True,
        brave_search_api_key="brave-key",
        brave_search_rate_limit=0.0,
        brave_search_soft_limit=2,
        brave_search_hard_limit=3,
        l0_url=None,
        l0_model="",
        l0_key="not-needed",
    )


def _service(cfg, brave) -> ProspectingAgentService:
    return ProspectingAgentService(
        cfg=cfg,
        repository=ProspectingRepository(cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        brave_client=brave,
    )


def _brief(**overrides) -> ProspectingBrief:
    base = dict(vertical="custom", target_description="negocios", city="Zaragoza")
    base.update(overrides)
    return ProspectingBrief(**base)


@pytest.mark.asyncio
async def test_service_reads_brave_limits_from_cfg(cfg):
    service = _service(cfg, _FakeBrave())

    status = service._brave_budget.status()

    assert status["soft_limit"] == 2
    assert status["hard_limit"] == 3


@pytest.mark.asyncio
async def test_discover_with_brave_stops_when_hard_limit_hit_mid_loop(cfg):
    brave = _FakeBrave()
    service = _service(cfg, brave)
    # generate_queries produce varias queries para un brief generico — de
    # sobra para superar el hard_limit=3 si no se frenara.
    brief = _brief(desired_count=20)
    run: dict = {"logs": [], "places_api_calls": 0}

    await service._discover_with_brave("run-1", run, brief)

    assert len(brave.calls) <= 3
    assert service._brave_budget.status()["calls"] == len(brave.calls)


@pytest.mark.asyncio
async def test_discover_with_brave_does_not_call_at_all_once_budget_already_exhausted(cfg):
    brave = _FakeBrave()
    service = _service(cfg, brave)
    await service._brave_budget.increment(3)  # ya al hard_limit
    brief = _brief(desired_count=20)
    run: dict = {"logs": [], "places_api_calls": 0}

    await service._discover_with_brave("run-1", run, brief)

    assert brave.calls == []


@pytest.mark.asyncio
async def test_enrich_candidate_with_brave_respects_budget(cfg):
    brave = _FakeBrave()
    service = _service(cfg, brave)
    await service._brave_budget.increment(3)  # ya al hard_limit
    brief = _brief()
    run: dict = {"logs": []}
    candidate = {"title": "Panadería El Horno", "address": "Zaragoza"}

    result = await service._enrich_candidate_with_brave("run-1", run, candidate, brief)

    assert result == {}
    assert brave.calls == []


@pytest.mark.asyncio
async def test_enrich_candidate_with_brave_calls_and_increments_when_under_budget(cfg):
    brave = _FakeBrave()
    service = _service(cfg, brave)
    brief = _brief()
    run: dict = {"logs": []}
    candidate = {"title": "Panadería El Horno", "address": "Zaragoza"}

    result = await service._enrich_candidate_with_brave("run-1", run, candidate, brief)

    assert len(brave.calls) == 1
    assert result["sources"] == ["brave"]
    assert service._brave_budget.status()["calls"] == 1
