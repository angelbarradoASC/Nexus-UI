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

# Fragmento LITERAL de los datos de arriba (el unico tipo de `dato` que se acepta).
_QUOTE = "mantenemos nuestra propia red de distribucion electrica"


async def _fit(cfg, llm, **kwargs):
    return await _service(cfg, llm)._assess_assets_fit(
        extracted=kwargs.pop("extracted", _EXTRACTED),
        business_profile=kwargs.pop("business_profile", _PROFILE),
        technical_audit=None,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_valid_match_with_a_literal_quote_is_kept(cfg):
    llm = _FakeLLM({
        "matches": [{
            "slug": "energia_ot_it",
            "dato": _QUOTE,
            "conexion": "Una red propia de distribucion implica un entorno donde TI y OT se cruzan.",
            "confianza": "alta",
        }],
        "resumen": "Encaja por su red de distribucion.",
    })

    fit = await _fit(cfg, llm)

    assert [m["slug"] for m in fit["matches"]] == ["energia_ot_it"]
    assert fit["matches"][0]["dato"] == _QUOTE
    assert "TI y OT" in fit["matches"][0]["conexion"]
    assert fit["matches"][0]["confianza"] == "alta"
    assert fit["sin_encaje"] is False
    assert fit["estado"] == "analizado"


@pytest.mark.asyncio
async def test_quote_matching_ignores_case_accents_and_punctuation(cfg):
    llm = _FakeLLM({"matches": [{
        "slug": "energia_ot_it",
        "dato": "Mantenemos NUESTRA propia red de distribución eléctrica",
        "conexion": "x", "confianza": "media",
    }]})

    fit = await _fit(cfg, llm)

    assert [m["slug"] for m in fit["matches"]] == ["energia_ot_it"]


@pytest.mark.asyncio
async def test_invented_slug_is_discarded(cfg):
    llm = _FakeLLM({"matches": [{"slug": "servicio_inventado", "dato": _QUOTE, "conexion": "x", "confianza": "alta"}]})

    fit = await _fit(cfg, llm)

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_paraphrase_that_is_not_in_the_data_is_discarded(cfg):
    """Bug real visto en vivo: 'opera con telemetria a gran escala' venia del
    catalogo, no de la empresa. Un dato que no esta tal cual en los datos no es
    un hecho — se descarta aunque comparta palabras sueltas con ellos."""
    llm = _FakeLLM({"matches": [{
        "slug": "energia_ot_it",
        "dato": "opera parques eolicos con telemetria a gran escala",
        "conexion": "x", "confianza": "alta",
    }]})

    fit = await _fit(cfg, llm)

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_quote_copied_from_the_catalogue_instead_of_the_company_is_discarded(cfg):
    llm = _FakeLLM({"matches": [{
        "slug": "energia_ot_it",
        "dato": "data lakes para telemetria IoT con retencion configurable",
        "conexion": "x", "confianza": "alta",
    }]})

    fit = await _fit(cfg, llm)

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_a_quote_shorter_than_three_words_is_discarded(cfg):
    llm = _FakeLLM({"matches": [{"slug": "energia_ot_it", "dato": "red electrica", "conexion": "x", "confianza": "alta"}]})

    fit = await _fit(cfg, llm)

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_proposals_without_any_citable_data_are_inconclusive_not_no_fit(cfg):
    """Si el modelo propone encajes pero ninguno se sostiene, NO es 'no
    encaja': es que no se puede afirmar nada."""
    llm = _FakeLLM({"matches": [
        {"slug": "aegis", "dato": "", "conexion": "x", "confianza": "alta"},
        {"slug": "seguridad_nis2", "dato": "cientos de hospitales por toda Latinoamerica", "conexion": "x", "confianza": "alta"},
    ]})

    fit = await _fit(cfg, llm)

    assert fit["estado"] == "inconcluso"
    assert fit["sin_encaje"] is None
    assert "2 encaje(s)" in fit["motivo"]


@pytest.mark.asyncio
async def test_only_the_supported_matches_survive_when_some_are_not(cfg):
    llm = _FakeLLM({"matches": [
        {"slug": "energia_ot_it", "dato": _QUOTE, "conexion": "x", "confianza": "alta"},
        {"slug": "aegis", "dato": "cumple ISO 27001 desde 2015", "conexion": "x", "confianza": "alta"},
    ]})

    fit = await _fit(cfg, llm)

    assert [m["slug"] for m in fit["matches"]] == ["energia_ot_it"]
    assert fit["estado"] == "analizado"


@pytest.mark.asyncio
async def test_unknown_confidence_falls_back_to_baja(cfg):
    llm = _FakeLLM({"matches": [{"slug": "energia_ot_it", "dato": _QUOTE, "conexion": "x", "confianza": "segurisima"}]})

    fit = await _fit(cfg, llm)

    assert fit["matches"][0]["confianza"] == "baja"


@pytest.mark.asyncio
async def test_deactivated_offering_cannot_be_matched(cfg):
    llm = _FakeLLM({"matches": [{"slug": "energia_ot_it", "dato": _QUOTE, "conexion": "x", "confianza": "alta"}]})
    service = _service(cfg, llm)
    service.offerings.set_activo("energia_ot_it", False)

    fit = await service._assess_assets_fit(extracted=_EXTRACTED, business_profile=_PROFILE, technical_audit=None)

    assert fit["matches"] == []


@pytest.mark.asyncio
async def test_prompt_carries_catalogue_cautions_and_regulations(cfg):
    llm = _FakeLLM({"matches": []})

    await _fit(cfg, llm)

    sent = llm.prompts[0]
    assert "NO afirmar:" in sent
    assert "roadmap" in sent.lower()
    assert "slug=nis2" in sent
    assert "slug=assets_perfil" not in sent


@pytest.mark.asyncio
async def test_extra_context_reaches_the_prompt_and_can_be_quoted(cfg):
    llm = _FakeLLM({"matches": [{
        "slug": "seguridad_nis2",
        "dato": "Opera distribucion electrica propia y telecomunicaciones",
        "conexion": "Dos sectores bajo NIS2.", "confianza": "media",
    }]})

    fit = await _fit(
        cfg, llm,
        extracted={"name": "Grupo X", "website": "https://x.example.com", "notes": []},
        business_profile={"what_they_do": ""},
        extra_context="Opera distribucion electrica propia y telecomunicaciones (fibra).",
    )

    assert "Informacion adicional" in llm.prompts[0]
    assert [m["slug"] for m in fit["matches"]] == ["seguridad_nis2"]


@pytest.mark.asyncio
async def test_disabled_llm_returns_not_analyzed_without_calling(cfg):
    llm = _FakeLLM({"matches": [{"slug": "aegis", "dato": _QUOTE, "conexion": "x", "confianza": "alta"}]})
    llm.enabled = False

    fit = await _fit(cfg, llm)

    assert fit["estado"] == "no_analizado"
    assert fit["sin_encaje"] is None
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_degraded_llm_is_reported_as_not_analyzed_never_as_no_fit(cfg):
    """Bug real encontrado en vivo: un ReadTimeout del LLM local devolvia
    extract_json -> {} y las 3 empresas salian 'sin encaje', como si se
    hubiera concluido que no encajan. 'No he podido analizar' y 'no encaja'
    son cosas distintas."""
    fit = await _fit(cfg, _FakeLLM({}))

    assert fit["estado"] == "no_analizado"
    assert fit["sin_encaje"] is None
    assert "timeout" in fit["motivo"]


@pytest.mark.asyncio
async def test_a_real_conclusion_of_no_fit_is_marked_as_analyzed(cfg):
    llm = _FakeLLM({"matches": [], "sin_encaje": True, "resumen": "No encaja en nada del catalogo."})

    fit = await _fit(cfg, llm)

    assert fit["estado"] == "analizado"
    assert fit["sin_encaje"] is True


@pytest.mark.asyncio
async def test_llm_exception_is_reported_as_not_analyzed(cfg):
    class _Boom(_FakeLLM):
        async def extract_json(self, **_kwargs):
            raise RuntimeError("conexion rechazada")

    fit = await _fit(cfg, _Boom({}))

    assert fit["estado"] == "no_analizado"
    assert "RuntimeError" in fit["motivo"]


@pytest.mark.asyncio
async def test_analyze_company_fit_runs_the_whole_chain_on_a_single_website(cfg):
    llm = _FakeLLM({
        "what_they_do": "Opera parques eolicos y una red de distribucion electrica en Aragon",
        "friction_points": [], "improvement_opportunities": [], "digital_maturity": "medio",
        "target_audience": "", "value_prop": "",
        "matches": [{"slug": "energia_ot_it", "dato": _QUOTE, "conexion": "x", "confianza": "alta"}],
    })

    result = await _service(cfg, llm).analyze_company_fit(website="eolicaebro.example.com")

    assert result["status"] == "ok"
    assert result["company"]["domain"] == "eolicaebro.example.com"
    assert [m["slug"] for m in result["assets_fit"]["matches"]] == ["energia_ot_it"]


@pytest.mark.asyncio
async def test_analyze_company_fit_requires_a_website(cfg):
    result = await _service(cfg, _FakeLLM({})).analyze_company_fit(website="  ")

    assert result["status"] == "error"
