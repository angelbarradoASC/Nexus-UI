"""tests/unit/test_grant_fit_classifier.py

ProspectingAgentService._classify_grant_fit — clasifica un lead ya
cualificado contra el catalogo REAL de ayudas (GrantsRepository), pedido
explicito del usuario: "busca el lead, mira a ver en cual encaja mejor, y
continua avanzando". Solo se ejecuta para verticales con grants_ambito en
su discovery_config (coste cero para restaurants/talleres/etc).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus.api.schemas.prospecting import ProspectingRunRequest
from nexus.prospecting.grants import GrantsRepository
from nexus.prospecting.repository import ProspectingRepository
from nexus.prospecting.service import ProspectingAgentService


class _FakeConnector:
    async def get_companies(self, **kwargs):
        return []


class _FakeLLM:
    enabled = True
    descriptor = {"enabled": True, "provider": "fake", "base_url": "http://fake", "model": "fake", "dry_run": False}

    def __init__(self, response: dict):
        self._response = response
        self.calls = 0

    async def extract_json(self, *, system_prompt, user_prompt, schema_hint):
        self.calls += 1
        return dict(self._response)


@pytest.fixture
def prospecting_cfg(tmp_path):
    return SimpleNamespace(
        prospecting_data_dir=str(tmp_path / "prospecting"),
        assets_crm_base_url="http://127.0.0.1:8000",
        assets_crm_username="", assets_crm_password="",
        prospecting_http_timeout_seconds=5, prospecting_user_agent="test-agent",
        prospecting_max_pages_per_site=3, local_llm_enabled=False,
        prospecting_user_agent_extra="", obscura_binary_path="",
        google_places_api_key=None, google_places_enabled=False,
        google_places_rate_limit=0.5, google_places_max_results_per_query=20,
        brave_search_api_key="brave-key", brave_search_enabled=False,
        brave_search_rate_limit=0.0, brave_search_soft_limit=None, brave_search_hard_limit=None,
        local_llm_base_url=None, l0_url=None, l0_model="", l0_key="not-needed",
    )


def _service(prospecting_cfg, *, llm) -> ProspectingAgentService:
    return ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        llm_client=llm,
        grants_repository=GrantsRepository(prospecting_cfg.prospecting_data_dir),
    )


@pytest.mark.asyncio
async def test_classify_grant_fit_returns_validated_match(prospecting_cfg):
    llm = _FakeLLM({"matches": [{"slug": "kit_consulting", "motivo": "empresa mediana con procesos manuales", "importe_estimado": "18.000€"}]})
    service = _service(prospecting_cfg, llm=llm)
    brief = service._normalize_brief(
        ProspectingRunRequest(vertical="ia_adopcion", target_description="empresa mediana", city="Zaragoza")
    )

    matches = await service._classify_grant_fit(
        extracted={"name": "Empresa Test", "notes": []},
        business_profile={"what_they_do": "fabricacion", "digital_maturity": "bajo", "friction_points": []},
        brief=brief,
    )

    assert len(matches) == 1
    assert matches[0]["slug"] == "kit_consulting"
    assert matches[0]["nombre"] == "Kit Consulting"
    assert matches[0]["motivo"] == "empresa mediana con procesos manuales"


@pytest.mark.asyncio
async def test_classify_grant_fit_rejects_slug_not_in_real_catalog(prospecting_cfg):
    """El LLM nunca puede colar una ayuda que no exista de verdad — mismo
    guardarrail que ya usa la resolucion de verticales."""
    llm = _FakeLLM({"matches": [{"slug": "ayuda_inventada_por_el_llm", "motivo": "x", "importe_estimado": ""}]})
    service = _service(prospecting_cfg, llm=llm)
    brief = service._normalize_brief(
        ProspectingRunRequest(vertical="ia_adopcion", target_description="empresa", city="Zaragoza")
    )

    matches = await service._classify_grant_fit(extracted={"name": "X"}, business_profile={}, brief=brief)

    assert matches == []


@pytest.mark.asyncio
async def test_classify_grant_fit_skips_verticals_without_grants_ambito(prospecting_cfg):
    """restaurants/talleres/etc no tienen grants_ambito — cero coste extra,
    ni siquiera se llama al LLM."""
    llm = _FakeLLM({"matches": [{"slug": "kit_consulting", "motivo": "x", "importe_estimado": ""}]})
    service = _service(prospecting_cfg, llm=llm)
    brief = service._normalize_brief(
        ProspectingRunRequest(vertical="restaurants", city="Zaragoza")
    )

    matches = await service._classify_grant_fit(extracted={"name": "X"}, business_profile={}, brief=brief)

    assert matches == []
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_classify_grant_fit_empty_when_llm_disabled(prospecting_cfg):
    llm = _FakeLLM({"matches": [{"slug": "kit_consulting", "motivo": "x", "importe_estimado": ""}]})
    llm.enabled = False
    service = _service(prospecting_cfg, llm=llm)
    brief = service._normalize_brief(
        ProspectingRunRequest(vertical="ia_adopcion", target_description="empresa", city="Zaragoza")
    )

    matches = await service._classify_grant_fit(extracted={"name": "X"}, business_profile={}, brief=brief)

    assert matches == []


def test_extract_employee_hint_finds_real_mention(prospecting_cfg):
    service = _service(prospecting_cfg, llm=_FakeLLM({}))
    hint = service._extract_employee_hint({"notes": ["Empresa con 120 empleados en Zaragoza"]})
    assert "120" in hint
    assert "no verificada" in hint


def test_extract_employee_hint_honest_when_not_mentioned(prospecting_cfg):
    service = _service(prospecting_cfg, llm=_FakeLLM({}))
    hint = service._extract_employee_hint({"notes": ["Peluqueria en el centro de Zaragoza"]})
    assert hint == "no mencionado en el texto disponible"
