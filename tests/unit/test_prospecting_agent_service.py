from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus.prospecting.brave import BraveSearchClient, BraveSearchSettings
from nexus.prospecting.llm import LocalLLMClient, LocalLLMSettings
from nexus.prospecting.repository import ProspectingRepository
from nexus.prospecting.scoring import ProspectScorer
from nexus.prospecting.service import ProspectingAgentService
from nexus.prospecting.validators import EmailValidator
from nexus.api.routes.prospecting import _fallback_parse, _sanitize_vertical_from_text


class _FakeConnector:
    def __init__(self) -> None:
        self.created_payloads = []
        self.notes = []
        self.tags = []

    configured = True

    async def find_company_by_domain(self, domain: str):
        return None

    async def find_company_by_email(self, email: str):
        return None

    async def find_company_by_name(self, name: str):
        return None

    async def list_pipeline(self):
        return {"companies": []}

    async def create_lead(self, payload):
        self.created_payloads.append(payload)
        return {"company": {"id": 77, "name": payload["name"]}}

    async def update_lead(self, entity_id: int, payload):
        return {"id": entity_id, **payload}

    async def add_note(self, entity_id: int, note):
        self.notes.append(note)
        return {"id": entity_id, **note}

    async def add_tag(self, entity_id: int, tag: str):
        self.tags.append((entity_id, tag))
        return {"id": entity_id, "tag": tag}


class _FakeBrave:
    enabled = True

    def __init__(self) -> None:
        self.calls = []

    async def search(self, *, run_id: str, query: str, country: str = "es", language: str = "es", count: int = 10, offset: int = 0):
        self.calls.append({"run_id": run_id, "query": query, "count": count})
        return {
            "provider": "brave",
            "query": query,
            "timestamp": "2026-06-04T10:00:00+00:00",
            "results": [
                {
                    "title": "Restaurante Fuego Zaragoza",
                    "url": "https://fuego.example.com",
                    "description": "Restaurante para grupos, eventos y reservas online en Zaragoza",
                }
            ],
        }


class _FakePlaces:
    enabled = True

    def __init__(self, results=None, api_calls: int = 1) -> None:
        self._results = list(results or [])
        self._api_calls = api_calls

    async def search_by_brief(self, *, vertical: str, geography: str, max_results: int, language: str):
        return list(self._results), self._api_calls


def _sample_places_result() -> dict:
    return {
        "place_id": "place-1",
        "title": "Restaurante Fuego Zaragoza",
        "url": "https://fuego.example.com",
        "description": "Calle Mayor 7, Zaragoza",
        "phone": "976123123",
        "address": "Calle Mayor 7, Zaragoza",
        "rating": 4.7,
        "rating_count": 128,
        "google_types": ["restaurant"],
        "source": "google_places",
    }


class _FakeExtractor:
    async def extract(self, *, url: str, vertical: str):
        return {
            "name": "Restaurante Fuego",
            "website": url,
            "domain": "fuego.example.com",
            "emails": ["reservas@fuego.example.com"],
            "phones": ["976123123"],
            "address": "Calle Mayor 7",
            "city": "Zaragoza",
            "province": "Zaragoza",
            "contact_form_only": False,
            "social_links": ["https://instagram.com/fuego"],
            "source_url": url,
            "evidence_urls": [url + "/contacto"],
            "quality_signals": ["reservas", "eventos", "terraza"],
            "notes": ["Fuente prioritaria"],
        }


class _FakeDomainValidator:
    async def validate(self, domain: str):
        return {"domain": domain, "dns_valid": True}


class _FakeMXValidator:
    async def validate(self, domain: str):
        return {"domain": domain, "mx_valid": True, "hosts": ["mx.example.com"]}


class _FakeOrchestrationLLM:
    def __init__(self, response: dict, overrides: dict[str, dict] | None = None) -> None:
        self._response = response
        self._overrides = overrides or {}

    enabled = True
    descriptor = {
        "enabled": True,
        "provider": "fake",
        "base_url": "http://fake-llm",
        "model": "fake-model",
        "dry_run": False,
    }

    async def extract_json(self, *, system_prompt: str, user_prompt: str, schema_hint: dict):
        for prompt_key, payload in self._overrides.items():
            if prompt_key in system_prompt:
                return dict(payload)
        return dict(self._response)


@pytest.fixture
def prospecting_cfg(tmp_path):
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
        llm_l0_url=None,
        l0_url=None,
        l0_model="",
        l0_key="not-needed",
    )


def test_query_generation_for_public_administration(prospecting_cfg):
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        brave_client=_FakeBrave(),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )
    queries = service.generate_queries(
        service._normalize_brief(
            {
                "vertical": "public_administration",
                "city": "Torrejón de la Calzada",
                "province": "Madrid",
                "must_have": ["web oficial", "telefono"],
            }
        )
    )
    assert any("ayuntamiento" in query.lower() for query in queries)
    assert any("sede electrónica" in query.lower() or "sede electronica" in query.lower() for query in queries)


def test_interpret_helpers_map_dental_clinics_to_salud():
    parsed = _fallback_parse("Quiero que me busques clinicas dentales en la zona de madrid sur cerca de parla")
    assert parsed["vertical"] == "salud"

    sanitized = _sanitize_vertical_from_text(
        {"vertical": "inmobiliaria"},
        "Quiero que me busques clinicas dentales en la zona de madrid sur cerca de parla",
    )
    assert sanitized["vertical"] == "custom"
    assert sanitized["vertical_created"] is False


def test_interpret_helpers_create_a_new_vertical_when_unknown():
    text = "Quiero que me busques academias de baile en Toledo"

    parsed = _fallback_parse(text)
    assert parsed["vertical"] != "custom"
    assert parsed["vertical"]

    sanitized = _sanitize_vertical_from_text(
        {"vertical": "custom", "target_description": "academias de baile"},
        text,
    )
    assert sanitized["vertical"] == "custom"
    assert sanitized["vertical_created"] is False


def test_query_generation_for_restaurants(prospecting_cfg):
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        brave_client=_FakeBrave(),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )
    queries = service.generate_queries(
        service._normalize_brief(
            {
                "vertical": "restaurants",
                "city": "Zaragoza",
                "desired_count": 30,
            }
        )
    )
    assert any("restaurante" in query.lower() for query in queries)
    assert any("eventos empresa" in query.lower() for query in queries)


def test_email_validator_flags_generic_and_personal():
    validator = EmailValidator()
    generic = validator.validate("info@empresa.com")
    personal = validator.validate("maria@gmail.com")

    assert generic["format_valid"] is True
    assert generic["is_generic"] is True
    assert personal["is_personal"] is True


def test_restaurant_scoring_is_vertical_aware():
    scorer = ProspectScorer()
    payload = scorer.score(
        {
            "website": "https://fuego.example.com",
            "dns_valid": True,
            "mx_valid": True,
            "email": "reservas@fuego.example.com",
            "phone": "976123123",
            "contact_form_only": False,
            "social_links": ["https://instagram.com/fuego"],
            "quality_signals": ["reservas", "eventos", "terraza"],
            "is_premium": True,
            "crm_duplicate": None,
        },
        vertical="restaurants",
        minimum_score=50,
    )
    assert payload["score"] >= 50
    assert payload["accepted"] is True


def test_public_scoring_values_official_contact():
    scorer = ProspectScorer()
    payload = scorer.score(
        {
            "website": "https://ayuntamiento.example.es",
            "official_website": True,
            "dns_valid": True,
            "mx_valid": True,
            "email": "informatica@ayuntamiento.es",
            "phone": "918000000",
            "contact_role": "Concejalia de Nuevas Tecnologias",
            "contact_person": "Ana Perez",
            "quality_signals": ["administracion electronica", "modernizacion"],
            "contact_form_only": False,
            "crm_duplicate": None,
        },
        vertical="public_administration",
        minimum_score=50,
    )
    assert payload["score"] >= 80
    assert payload["priority"] == "Alta"


@pytest.mark.asyncio
async def test_push_valid_to_crm_previews_payloads(prospecting_cfg):
    connector = _FakeConnector()
    brave = _FakeBrave()
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=connector,
        brave_client=brave,
        places_client=_FakePlaces([_sample_places_result()]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    run = await service.run(
        {
            "vertical": "restaurants",
            "city": "Zaragoza",
            "desired_count": 1,
            "minimum_score": 50,
            "dry_run": True,
        }
    )
    pushed = await service.push_valid_to_crm(run["run_id"], dry_run=True)

    assert pushed["status"] == "accepted"
    assert pushed["pushed_count"] == 1
    assert pushed["results"][0]["company_payload"]["name"] == "Restaurante Fuego"
    assert pushed["results"][0]["tags_note_payload"]["content"].startswith("Tags Nexus aplicadas: ")


@pytest.mark.asyncio
async def test_push_to_crm_consolidates_all_tags_into_single_activity(prospecting_cfg):
    connector = _FakeConnector()
    brave = _FakeBrave()
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=connector,
        brave_client=brave,
        places_client=_FakePlaces([_sample_places_result()]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    run = await service.run(
        {
            "vertical": "restaurants",
            "city": "Zaragoza",
            "desired_count": 1,
            "minimum_score": 50,
            "dry_run": True,
        }
    )
    pushed = await service.push_valid_to_crm(run["run_id"], dry_run=False)

    assert pushed["status"] == "accepted"
    assert connector.tags == []
    assert len(connector.notes) == 2
    assert "Prospectado por Nexus ProspectingAgent." in connector.notes[0]["content"]
    assert connector.notes[1]["content"].startswith("Tags Nexus aplicadas: ")
    assert "prospeccion-nexus" in connector.notes[1]["content"]


@pytest.mark.asyncio
async def test_full_run_persists_results_and_summary(prospecting_cfg):
    brave = _FakeBrave()
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        brave_client=brave,
        places_client=_FakePlaces([_sample_places_result()]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    result = await service.run(
        {
            "vertical": "restaurants",
            "city": "Zaragoza",
            "desired_count": 1,
            "minimum_score": 40,
            "dry_run": True,
        }
    )
    stored = await service.get_run(result["run_id"])

    assert result["status"] == "completed"
    assert stored["results"][0]["name"] == "Restaurante Fuego"
    assert stored["results"][0]["score"] >= 40
    assert stored["summary"]["usable_results"] == 1
    assert stored["discovery_source"] == "google_places"
    assert stored["results"][0]["enrichment_sources"] == ["brave"]
    assert brave.calls, "Brave debe ejecutarse como enriquecimiento del candidato"
    assert stored["orchestration"]["autonomous_agents"]["completed_agents"] >= 6
    assert any(agent["agent_id"] == "crm_packager" for agent in stored["orchestration"]["autonomous_agents"]["agents"])


@pytest.mark.asyncio
async def test_resume_run_reprocesses_failed_run(prospecting_cfg):
    brave = _FakeBrave()
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        brave_client=brave,
        places_client=_FakePlaces([_sample_places_result()]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )
    run = await service.run(
        {
            "vertical": "restaurants",
            "city": "Zaragoza",
            "desired_count": 1,
            "minimum_score": 40,
            "dry_run": True,
        }
    )
    await service._repository.update_run(run["run_id"], lambda current: current | {"status": "failed", "error": "forced"})
    resumed = await service.resume_run(run["run_id"])

    assert resumed["status"] == "completed"


@pytest.mark.asyncio
async def test_local_llm_client_json_extraction_with_mock_transport():
    client = LocalLLMClient(
        settings=LocalLLMSettings(
            base_url="http://localhost:1234/v1",
            model="qwen-test",
            enabled=True,
            retries=1,
            timeout=5,
        )
    )

    async def handler(request):
        return __import__("httpx").Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"queries":["restaurante zaragoza eventos","restaurante premium zaragoza"]}'
                        }
                    }
                ]
            },
        )

    transport = __import__("httpx").MockTransport(handler)
    import httpx

    original_client = httpx.AsyncClient

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = _PatchedClient
    try:
        payload = await client.extract_json(
            system_prompt="json only",
            user_prompt="dame queries",
            schema_hint={"queries": []},
        )
    finally:
        httpx.AsyncClient = original_client

    assert payload["queries"][0].startswith("restaurante")


@pytest.mark.asyncio
async def test_brave_client_dry_run_persists_raw(tmp_path):
    repository = ProspectingRepository(tmp_path / "prospecting")
    client = BraveSearchClient(
        settings=BraveSearchSettings(api_key=None, enabled=False, rate_limit_seconds=0.0),
        repository=repository,
        dry_run=True,
    )
    payload = await client.search(run_id="run-1", query="restaurantes zaragoza", count=5)
    raw_files = list((tmp_path / "prospecting" / "raw").glob("*.json"))

    assert payload["dry_run"] is True
    assert raw_files, "Debe persistir evidencia bruta incluso en dry-run"


@pytest.mark.asyncio
async def test_orchestrate_brief_refines_prompt_and_plans_sources(prospecting_cfg):
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        llm_client=_FakeOrchestrationLLM(
            {
                "target_description": "restaurantes premium para eventos de empresa",
                "must_have": ["Reservas online", "Email directo"],
                "nice_to_have": ["Terraza", "Buenas reseñas"],
                "exclude": ["franquicias", "directorios"],
                "crm_tags": ["premium", "zaragoza"],
                "preferred_sources": ["google_places", "brave"],
                "notes": "Mantengo geografía y refino criterios comerciales.",
            },
            overrides={
                "sales.prospecting.guardrails": {
                    "summary": "Guardrails aplicados antes de tocar el brief.",
                    "warnings": ["Prompt corto pero usable."],
                    "guardrails_applied": ["No inventar geografia."],
                },
                "sales.prospecting.source_strategy": {
                    "summary": "Google Places primero y Brave como cobertura extra.",
                    "source_bias": "google_places",
                    "warnings": [],
                },
            },
        ),
        brave_client=_FakeBrave(),
        places_client=_FakePlaces([]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    orchestrated = await service.orchestrate_brief(
        {
            "vertical": "restaurants",
            "city": "Zaragoza",
            "province": "Zaragoza",
            "desired_count": 10,
            "represented_by": "assets",
            "target_description": "restaurantes zaragoza",
        },
        original_text="Busca restaurantes premium en Zaragoza para eventos de empresa y evita franquicias.",
    )

    assert orchestrated["brief"]["target_description"] == "restaurantes premium para eventos de empresa"
    assert orchestrated["brief"]["city"] == "Zaragoza"
    assert orchestrated["brief"]["desired_count"] == 10
    assert orchestrated["brief"]["must_have"] == ["Reservas online", "Email directo"]
    assert orchestrated["orchestration"]["refinement_applied"] is True
    assert orchestrated["orchestration"]["source_plan"]["sources"][0]["name"] == "google_places"
    assert orchestrated["orchestration"]["autonomous_agents"]["completed_agents"] == 3
    assert any(agent["agent_id"] == "brief_guardian" for agent in orchestrated["orchestration"]["autonomous_agents"]["agents"])


@pytest.mark.asyncio
async def test_guardian_drops_fake_missing_city_warning_when_brief_has_city_and_province(prospecting_cfg):
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        llm_client=_FakeOrchestrationLLM(
            {
                "target_description": "asesorias fiscales y legales",
                "must_have": ["Email directo"],
                "nice_to_have": [],
                "exclude": ["directorios"],
                "crm_tags": ["prospeccion-nexus"],
                "preferred_sources": ["google_places", "brave"],
                "notes": "Mantengo geografia y marca.",
            },
            overrides={
                "sales.prospecting.guardrails": {
                    "summary": "Guardrails preparados antes de ejecutar la prospeccion.",
                    "warnings": ["El prompt no especifica una ciudad dentro de Madrid, lo que puede resultar en resultados inapropiados."],
                    "guardrails_applied": ["No inventar geografia."],
                },
                "sales.prospecting.source_strategy": {
                    "summary": "Google Places primero y Brave como apoyo.",
                    "source_bias": "google_places",
                    "warnings": [],
                },
            },
        ),
        brave_client=_FakeBrave(),
        places_client=_FakePlaces([]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    orchestrated = await service.orchestrate_brief(
        {
            "vertical": "asesoria",
            "city": "Pinto",
            "province": "Madrid",
            "desired_count": 20,
            "represented_by": "assets",
            "target_description": "asesorias fiscales y legales",
        },
        original_text="Quiero que me encuentres asesorias fiscales y legales por la zona de Pinto (Madrid)",
    )

    guardian = next(
        agent
        for agent in orchestrated["orchestration"]["autonomous_agents"]["agents"]
        if agent["agent_id"] == "brief_guardian"
    )
    assert guardian["warnings"] == []


@pytest.mark.asyncio
async def test_source_plan_normalizes_llm_preference_to_places_first_when_geography_exists(prospecting_cfg):
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        llm_client=_FakeOrchestrationLLM(
            {
                "target_description": "inmobiliarias residenciales",
                "must_have": ["Web propia"],
                "nice_to_have": ["LinkedIn"],
                "exclude": ["portales", "directorios"],
                "crm_tags": ["inmo"],
                "preferred_sources": ["brave", "google_places"],
                "notes": "Refino criterios sin tocar geografia.",
            },
            overrides={
                "sales.prospecting.guardrails": {
                    "summary": "Guardrails preparados.",
                    "warnings": [],
                    "guardrails_applied": ["No inventar geografia."],
                },
                "sales.prospecting.source_strategy": {
                    "summary": "Google Places primero y Brave de refuerzo.",
                    "source_bias": "google_places",
                    "warnings": [],
                },
            },
        ),
        brave_client=_FakeBrave(),
        places_client=_FakePlaces([]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    orchestrated = await service.orchestrate_brief(
        {
            "vertical": "inmobiliaria",
            "city": "Pinto",
            "province": "Madrid",
            "desired_count": 15,
            "represented_by": "assets",
            "target_description": "inmobiliarias en Pinto",
        },
        original_text="Quiero inmobiliarias en Pinto con web propia y evitar portales",
    )

    sources = orchestrated["orchestration"]["source_plan"]["sources"]
    assert [source["name"] for source in sources] == ["google_places"]
    assert orchestrated["orchestration"]["source_plan"]["enrichment_sources"][0]["name"] == "brave"


@pytest.mark.asyncio
async def test_llm_classification_keeps_core_identity_fields_stable(prospecting_cfg):
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        llm_client=_FakeOrchestrationLLM(
            {
                "relevant": False,
                "name": "Inmobiliaria Madrid",
                "city": "Toledo",
                "province": "Toledo",
                "contact_person": "info@mrhouse.es, 914126937",
                "contact_role": "Central comercial",
                "quality_signals": ["foo", "bar"],
                "is_premium": True,
                "official_website": True,
                "reason": "LLM intentaba sobreescribir la identidad del lead.",
                "notes": "LLM intentaba sobreescribir la identidad del lead.",
            }
        ),
        brave_client=_FakeBrave(),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    result = await service._extract_candidate(
        "run-1",
        {},
        {
            "title": "Inmobiliaria MR House Real Estate",
            "url": "http://www.mrhouse.es",
            "description": "Inmobiliaria en Parla",
            "address": "Parla, Madrid",
            "phone": "914126937",
        },
        service._normalize_brief(
            {
                "vertical": "inmobiliaria",
                "city": "Parla",
                "province": "Madrid",
                "desired_count": 1,
                "minimum_score": 40,
            }
        ),
    )

    assert result["name"] == "Restaurante Fuego"
    assert result["city"] == "Zaragoza"
    assert result["province"] == "Zaragoza"
    assert result["contact_person"] == ""
    assert result["contact_role"] == "Central comercial"
    assert "foo" in result["quality_signals"]


@pytest.mark.asyncio
async def test_run_keeps_results_empty_when_places_returns_empty_and_brave_does_not_discover(prospecting_cfg):
    brave = _FakeBrave()
    service = ProspectingAgentService(
        cfg=prospecting_cfg,
        repository=ProspectingRepository(prospecting_cfg.prospecting_data_dir),
        connector=_FakeConnector(),
        brave_client=brave,
        places_client=_FakePlaces([]),
        extractor=_FakeExtractor(),
        domain_validator=_FakeDomainValidator(),
        mx_validator=_FakeMXValidator(),
    )

    result = await service.run(
        {
            "vertical": "restaurants",
            "city": "Zaragoza",
            "province": "Zaragoza",
            "desired_count": 1,
            "minimum_score": 40,
            "dry_run": True,
        }
    )
    stored = await service.get_run(result["run_id"])

    assert result["status"] == "completed"
    assert stored["results"] == []
    assert stored["orchestration"]["source_plan"]["sources"][0]["name"] == "google_places"
    assert any(str(query).startswith("[Places]") for query in stored["queries"])
    assert brave.calls == []
