"""tests/unit/test_web_search_chat.py

PEPO respondiendo "cuales son los trending topics hoy?" (skill web.busqueda).
Bug real visto en vivo: web.busqueda no tenia handler en el coordinador, asi
que el LLM contestaba "no tengo acceso a informacion en tiempo real" sin haber
buscado nada — aunque Brave estaba configurado. Ahora busca de verdad (Brave
con el MISMO presupuesto mensual que la prospeccion, DuckDuckGo de respaldo)
y responde solo con lo encontrado.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus.api.schemas.chat import ChatRequest
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator
from nexus.prompts import resolve_prompt_sync
from nexus.prospecting.repository import ProspectingRepository
from nexus.prospecting.service import ProspectingAgentService


# ── Servicio: Brave → presupuesto → DuckDuckGo ───────────────────────────────

class _FakeConnector:
    configured = True

    async def find_company_by_domain(self, domain):
        return None

    async def find_company_by_email(self, email):
        return None

    async def find_company_by_name(self, name):
        return None

    async def list_pipeline(self):
        return {"companies": []}


class _FakeBrave:
    def __init__(self, *, enabled=True, fail=False) -> None:
        self.enabled = enabled
        self._fail = fail
        self.calls: list[dict] = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail:
            raise RuntimeError("brave caido")
        return {"results": [{"title": "T", "url": "https://x.es", "description": "d", "age": "1 hour ago"}]}


class _FakeDdg:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search(self, *, run_id, query, max_results=None):
        self.calls.append(query)
        return {"results": [{"title": "D", "url": "https://ddg.es", "description": "snippet"}]}

    def is_directory_domain(self, url):
        return False


def _cfg(tmp_path, *, hard_limit=700):
    return SimpleNamespace(
        prospecting_data_dir=str(tmp_path / "prospecting"),
        assets_crm_base_url="http://127.0.0.1:8000", assets_crm_username="", assets_crm_password="",
        prospecting_http_timeout_seconds=5, prospecting_user_agent="t", prospecting_max_pages_per_site=3,
        local_llm_enabled=False, local_llm_base_url=None, local_llm_model="",
        local_llm_provider="openai_compatible", local_llm_timeout=10, local_llm_retries=1,
        local_llm_api_key="not-needed", brave_search_enabled=True, brave_search_api_key="k",
        brave_search_rate_limit=0.0, brave_search_soft_limit=1, brave_search_hard_limit=hard_limit,
        l0_url=None, l0_model="", l0_key="not-needed",
    )


def _service(tmp_path, brave, ddg, **cfg_kw) -> ProspectingAgentService:
    cfg = _cfg(tmp_path, **cfg_kw)
    return ProspectingAgentService(
        cfg=cfg, repository=ProspectingRepository(cfg.prospecting_data_dir),
        connector=_FakeConnector(), brave_client=brave, ddg_client=ddg,
    )


@pytest.mark.asyncio
async def test_web_search_uses_brave_and_counts_against_the_shared_budget(tmp_path):
    brave, ddg = _FakeBrave(), _FakeDdg()
    service = _service(tmp_path, brave, ddg)

    result = await service.web_search("trending hoy", freshness="pw")

    assert result["provider"] == "brave"
    assert result["results"][0]["url"] == "https://x.es"
    assert brave.calls[0]["freshness"] == "pw"
    assert ddg.calls == []
    assert service._brave_budget.status()["calls"] == 1


@pytest.mark.asyncio
async def test_web_search_falls_back_to_ddg_when_budget_is_exhausted(tmp_path):
    brave, ddg = _FakeBrave(), _FakeDdg()
    service = _service(tmp_path, brave, ddg, hard_limit=1)
    await service.web_search("primera")  # consume el unico permitido

    result = await service.web_search("segunda")

    assert result["provider"] == "ddg"
    assert "DuckDuckGo" in result["note"]
    assert len(brave.calls) == 1


@pytest.mark.asyncio
async def test_web_search_falls_back_to_ddg_when_brave_fails(tmp_path):
    brave, ddg = _FakeBrave(fail=True), _FakeDdg()
    service = _service(tmp_path, brave, ddg)

    result = await service.web_search("algo")

    assert result["provider"] == "ddg"
    assert result["results"][0]["description"] == "snippet"
    assert service._brave_budget.status()["calls"] == 0  # no se cobra una llamada fallida


@pytest.mark.asyncio
async def test_web_search_uses_ddg_when_brave_is_not_configured(tmp_path):
    brave, ddg = _FakeBrave(enabled=False), _FakeDdg()
    service = _service(tmp_path, brave, ddg)

    result = await service.web_search("algo")

    assert result["provider"] == "ddg"
    assert brave.calls == []


# ── Coordinador ──────────────────────────────────────────────────────────────

class _FakeProspecting:
    def __init__(self, result=None, *, boom=False) -> None:
        self._result = result or {"provider": "brave", "results": [], "note": ""}
        self._boom = boom
        self.queries: list[tuple] = []

    async def web_search(self, query, *, count=8, freshness=None, **_):
        self.queries.append((query, freshness))
        if self._boom:
            raise RuntimeError("sin red")
        return self._result


class _FakeRouter:
    def __init__(self, content="Resumen de prueba.", error=None) -> None:
        self.content, self.error = content, error
        self.calls: list[list[dict]] = []

    async def call(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(content=self.content, error=self.error)


def _coordinator(prospecting, router=None) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None, grafana=None, prometheus=None,
        incident_repository=MemoryIncidentRepository(), audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(), prospecting=prospecting, llm_router=router,
    )


_OVERRIDE = {"skill_id": "web.busqueda", "entities": {}}


@pytest.mark.asyncio
async def test_chat_searches_the_web_and_answers_from_the_results():
    prospecting = _FakeProspecting({
        "provider": "brave", "note": "",
        "results": [{"title": "Tendencias en X", "url": "https://t.example/x", "description": "Lista", "age": "2 hours ago"}],
    })
    router = _FakeRouter("Hoy destacan estos temas.")
    coordinator = _coordinator(prospecting, router)

    response = await coordinator.handle_chat(
        ChatRequest(message="trending topics en twitter hoy en españa"), resolution_override=_OVERRIDE
    )

    assert prospecting.queries == [("trending topics en twitter hoy en españa", "pw")]
    assert "Hoy destacan estos temas." in response.response
    assert "https://t.example/x" in response.response
    assert "brave" in response.response
    assert response.agent == "web-search"
    # el LLM recibe los resultados reales y la fecha, no solo la pregunta
    user_msg = router.calls[0][1]["content"]
    assert "Tendencias en X" in user_msg and "Fecha de hoy" in user_msg


@pytest.mark.asyncio
async def test_chat_says_so_honestly_when_the_search_returns_nothing():
    coordinator = _coordinator(_FakeProspecting(), _FakeRouter())

    response = await coordinator.handle_chat(
        ChatRequest(message="busca algo raro"), resolution_override=_OVERRIDE
    )

    assert "no me han llegado resultados" in response.response
    assert response.status == "degraded"


@pytest.mark.asyncio
async def test_chat_survives_a_search_exception():
    coordinator = _coordinator(_FakeProspecting(boom=True), _FakeRouter())

    response = await coordinator.handle_chat(
        ChatRequest(message="busca algo"), resolution_override=_OVERRIDE
    )

    assert response.status == "degraded"


@pytest.mark.asyncio
async def test_chat_still_lists_results_when_the_llm_fails():
    prospecting = _FakeProspecting({
        "provider": "ddg", "note": "Brave no está configurado; uso DuckDuckGo.",
        "results": [{"title": "Fuente", "url": "https://f.example", "description": "x"}],
    })
    coordinator = _coordinator(prospecting, _FakeRouter(content="", error="429"))

    response = await coordinator.handle_chat(
        ChatRequest(message="busca el precio"), resolution_override=_OVERRIDE
    )

    assert "https://f.example" in response.response
    assert "no he podido resumirlos" in response.response
    assert "DuckDuckGo" in response.response


# ── Identidad ────────────────────────────────────────────────────────────────

def test_general_prompt_identifies_as_pepo_not_jaina():
    """Bug real: el chat contestaba 'Soy JAINA' aunque la UI es PEPO."""
    prompt = resolve_prompt_sync("agent.general")

    assert "Eres PEPO" in prompt
    assert "Eres JAINA" not in prompt


# ── Router: no gastar busquedas de pago por un "hoy" suelto ──────────────────

@pytest.mark.parametrize("message", [
    "cuales son los trending topics en twitter hoy? dame los 10 primeros en españa",
    "busca el precio del bitcoin",
    "que noticias hay sobre python",
    "que pasa hoy en madrid",
])
def test_router_sends_real_web_questions_to_web_busqueda(message):
    from desktop.runtime.skill_router import DesktopSkillRouter

    assert DesktopSkillRouter().resolve(message).to_dict()["skill_id"] == "web.busqueda"


@pytest.mark.parametrize("message", [
    "tengo algun correo de hoy?",
    "que tal estas hoy",
    "como esta el servidor hoy",
])
def test_router_does_not_search_the_web_just_because_of_hoy(message):
    from desktop.runtime.skill_router import DesktopSkillRouter

    assert DesktopSkillRouter().resolve(message).to_dict()["skill_id"] != "web.busqueda"
