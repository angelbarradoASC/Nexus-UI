"""Tests del analisis de encaje con lo que ofrece Assets (service._assess_assets_fit)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus.prospecting.repository import ProspectingRepository
from nexus.prospecting.service import ProspectingAgentService


class _FakeLLM:
    enabled = True
    descriptor = {"enabled": True, "provider": "fake", "base_url": "", "model": "fake", "dry_run": False}

    def __init__(self, response: dict) -> None:
        self._response = response
        self.prompts: list[str] = []

    async def extract_json(self, *, system_prompt: str, user_prompt: str, schema_hint: dict):
        self.prompts.append(user_prompt)
        return dict(self._response)


class _FakeExtractor:
    async def extract(self, *, url, link_hints=None, quality_signal_tokens=None):
        return {
            "name": "Eolica del Ebro",
            "website": url,
            "domain": "eolicaebro.example.com",
            "notes": ["Operamos parques eolicos y mantenemos nuestra propia red de distribucion electrica en Aragon."],
            "quality_signals": [],
        }


class _FakeConnector:
    configured = True


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
        brave_search_enabled=False,
        brave_search_api_key="",
        brave_search_rate_limit=0.0,
        llm_l0_url=None,
        l0_url=None,
        l0_model="",
        l0_key="not-needed",
    )


def _service(cfg, llm: _FakeLLM) -> ProspectingAgentService:
    return ProspectingAgentService(
        cfg=cfg,
        repository=ProspectingRepository(cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        llm_client=llm,
        extractor=_FakeExtractor(),
    )


_PROFILE = {
    "what_they_do": "Opera parques eolicos y una red de distribucion electrica en Aragon",
    "target_audience": "", "digital_maturity": "medio",
    "friction_points": [], "improvement_opportunities": [],
}
_EXTRACTED = {
    "name": "Eolica del Ebro", "website": "https://eolicaebro.example.com",
    "notes": ["Operamos parques eolicos y mantenemos nuestra propia red de distribucion electrica en Aragon."],
}


@pytest.mark.asyncio
async def test_valid_match_with_grounded_evidence_is_kept(cfg):
    llm = _FakeLLM({
        "matches": [{
            "slug": "energia_ot_it",
            "evidencia": "Mantiene su propia red de distribucion electrica, entorno donde TI y OT se cruzan",
            "confianza": "alta",
        }],
        "resumen": "Encaja por su red de distribucion.",
    })

    fit = await _service(cfg, llm)._assess_assets_fit(
        extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None,
    )

    assert [m["slug"] for m in fit["matches"]] == ["energia_ot_it"]
    assert fit["matches"][0]["confianza"] == "alta"
    assert fit["sin_encaje"] is False


@pytest.mark.asyncio
async def test_invented_slug_is_discarded(cfg):
    llm = _FakeLLM({"matches": [{"slug": "servicio_inventado", "evidencia": "red de distribucion electrica", "confianza": "alta"}]})

    fit = await _service(cfg, llm)._assess_assets_fit(
        extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None,
    )

    assert fit["matches"] == []
    assert fit["sin_encaje"] is True


@pytest.mark.asyncio
async def test_match_whose_evidence_is_not_in_the_data_is_discarded(cfg):
    llm = _FakeLLM({"matches": [{
        "slug": "aegis",
        "evidencia": "Gestiona cientos de hospitales y clinicas dentales por toda Latinoamerica",
        "confianza": "alta",
    }]})

    fit = await _service(cfg, llm)._assess_assets_fit(
        extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None,
    )

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_match_without_evidence_is_discarded(cfg):
    llm = _FakeLLM({"matches": [{"slug": "aegis", "evidencia": "", "confianza": "alta"}]})

    fit = await _service(cfg, llm)._assess_assets_fit(
        extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None,
    )

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_unknown_confidence_falls_back_to_baja(cfg):
    llm = _FakeLLM({"matches": [{"slug": "energia_ot_it", "evidencia": "red de distribucion electrica", "confianza": "segurisima"}]})

    fit = await _service(cfg, llm)._assess_assets_fit(
        extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None,
    )

    assert fit["matches"][0]["confianza"] == "baja"


@pytest.mark.asyncio
async def test_deactivated_offering_cannot_be_matched(cfg):
    llm = _FakeLLM({"matches": [{"slug": "energia_ot_it", "evidencia": "red de distribucion electrica", "confianza": "alta"}]})
    service = _service(cfg, llm)
    service.offerings.set_activo("energia_ot_it", False)

    fit = await service._assess_assets_fit(extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None)

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_prompt_carries_catalogue_cautions_and_regulations(cfg):
    llm = _FakeLLM({"matches": []})

    await _service(cfg, llm)._assess_assets_fit(extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None)

    sent = llm.prompts[0]
    assert "NO afirmar:" in sent
    assert "roadmap" in sent.lower()
    assert "slug=nis2" in sent
    assert "slug=assets_perfil" not in sent


@pytest.mark.asyncio
async def test_extra_context_reaches_the_prompt_and_counts_as_evidence(cfg):
    llm = _FakeLLM({"matches": [{
        "slug": "seguridad_nis2",
        "evidencia": "Opera distribucion electrica y telecomunicaciones, dos sectores bajo NIS2",
        "confianza": "media",
    }]})

    fit = await _service(cfg, llm)._assess_assets_fit(
        extracted={"name": "Grupo X", "website": "https://x.example.com", "notes": []},
        business_profile={"what_they_do": ""},
        technical_audit=None,
        extra_context="Opera distribucion electrica propia y telecomunicaciones (fibra).",
    )

    assert "Informacion adicional" in llm.prompts[0]
    assert [m["slug"] for m in fit["matches"]] == ["seguridad_nis2"]


@pytest.mark.asyncio
async def test_disabled_llm_returns_no_fit_without_calling(cfg):
    llm = _FakeLLM({"matches": [{"slug": "aegis", "evidencia": "x", "confianza": "alta"}]})
    llm.enabled = False

    fit = await _service(cfg, llm)._assess_assets_fit(extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None)

    assert fit == {"matches": [], "sin_encaje": True, "resumen": ""}
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_analyze_company_fit_runs_the_whole_chain_on_a_single_website(cfg):
    llm = _FakeLLM({
        "what_they_do": "Opera parques eolicos y una red de distribucion electrica en Aragon",
        "friction_points": [], "improvement_opportunities": [], "digital_maturity": "medio",
        "target_audience": "", "value_prop": "",
        "matches": [{"slug": "energia_ot_it", "evidencia": "propia red de distribucion electrica", "confianza": "alta"}],
    })

    result = await _service(cfg, llm).analyze_company_fit(website="eolicaebro.example.com")

    assert result["status"] == "ok"
    assert result["company"]["domain"] == "eolicaebro.example.com"
    assert [m["slug"] for m in result["assets_fit"]["matches"]] == ["energia_ot_it"]


@pytest.mark.asyncio
async def test_analyze_company_fit_requires_a_website(cfg):
    result = await _service(cfg, _FakeLLM({})).analyze_company_fit(website="  ")

    assert result["status"] == "error"
