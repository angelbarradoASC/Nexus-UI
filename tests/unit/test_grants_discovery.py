"""tests/unit/test_grants_discovery.py

GrantsDiscoveryService — mantiene el catalogo de ayudas fresco. Pedido
explicito del usuario: una ayuda sembrada a mano hoy caduca sola con el
tiempo (mismo problema ya visto con el .env desincronizado del build).
Reutiliza los mismos clientes de busqueda (Brave/DDG) y LocalLLMClient que
ya usa ProspectingAgentService — se prueban aqui con fakes.
"""

from __future__ import annotations

import pytest

from nexus.prospecting.grants import GrantsRepository
from nexus.prospecting.grants_discovery import GrantsDiscoveryService


class _FakeSearchClient:
    def __init__(self, *, results=None, enabled=True):
        self._results = results if results is not None else [
            {"title": "Resultado real", "description": "algo encontrado", "url": "https://example.com"},
        ]
        self.enabled = enabled
        self.calls: list[str] = []

    async def search(self, *, run_id, query, **kwargs):
        self.calls.append(query)
        return {"results": self._results}


class _FakeLLM:
    def __init__(self, *, responses=None, enabled=True):
        self._responses = list(responses or [])
        self.enabled = enabled
        self.calls: list[dict] = []

    async def extract_json(self, *, system_prompt, user_prompt, schema_hint):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._responses.pop(0) if self._responses else {}


def _repo(tmp_path) -> GrantsRepository:
    return GrantsRepository(tmp_path)


@pytest.mark.asyncio
async def test_check_freshness_marks_expired_with_real_evidence(tmp_path):
    repo = _repo(tmp_path)
    llm = _FakeLLM(responses=[
        {"vigente": False, "vigente_hasta": "2026-01-01", "evidencia": "convocatoria cerrada segun la web oficial"},
        {"vigente": True, "vigente_hasta": "", "evidencia": ""},
        {"vigente": True, "vigente_hasta": "", "evidencia": ""},
    ])
    brave = _FakeSearchClient()
    service = GrantsDiscoveryService(grants=repo, llm=llm, brave=brave)

    result = await service.check_freshness()

    # list_all() ordena por ambito ASC, nombre ASC — "aragon" va antes que
    # "estatal", asi que la primera respuesta fake (vigente=False) le toca a
    # aragon_pyme_digitalizacion, no a kit_consulting. Se comprueba el
    # comportamiento (una expira con la evidencia real, las demas no),
    # no un slug concreto atado al orden de iteracion.
    assert result["status"] == "ok"
    assert len(result["expired"]) == 1
    expired_slug = result["expired"][0]
    assert repo.get(expired_slug).estado == "expirado"
    assert repo.get(expired_slug).vigente_hasta == "2026-01-01"
    still_active = [g for g in repo.list_all() if g.slug != expired_slug]
    assert all(g.estado == "activo" for g in still_active)


@pytest.mark.asyncio
async def test_check_freshness_never_expires_without_search_results(tmp_path):
    """Sin resultados de busqueda no hay evidencia real — no se debe marcar
    expirada una ayuda solo por no encontrar nada."""
    repo = _repo(tmp_path)
    llm = _FakeLLM(responses=[])
    brave = _FakeSearchClient(results=[])
    service = GrantsDiscoveryService(grants=repo, llm=llm, brave=brave)

    result = await service.check_freshness()

    assert result["expired"] == []
    assert repo.get("kit_consulting").estado == "activo"
    assert llm.calls == []  # ni se llega a preguntar al LLM sin evidencia


@pytest.mark.asyncio
async def test_check_freshness_skipped_when_llm_disabled(tmp_path):
    repo = _repo(tmp_path)
    llm = _FakeLLM(enabled=False)
    brave = _FakeSearchClient()
    service = GrantsDiscoveryService(grants=repo, llm=llm, brave=brave)

    result = await service.check_freshness()

    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_discover_new_adds_grant_as_pending_review(tmp_path):
    repo = _repo(tmp_path)
    llm = _FakeLLM(responses=[
        {"programas": [{
            "nombre": "Ayuda Nueva de Prueba", "criterios": "empresas tecnologicas",
            "min_employees": 20, "max_employees": 100, "importe_desc": "10.000€",
            "url": "https://example.com/ayuda", "vigente_hasta": "2026-12-31",
        }]},
    ])
    brave = _FakeSearchClient()
    service = GrantsDiscoveryService(grants=repo, llm=llm, brave=brave)

    result = await service.discover_new(ambito="estatal", hints=["nuevas ayudas ia 2026"])

    assert result["status"] == "ok"
    assert len(result["discovered"]) == 1
    grant = repo.get(result["discovered"][0])
    assert grant.nombre == "Ayuda Nueva de Prueba"
    assert grant.estado == "pendiente_revision"
    assert grant.ambito == "estatal"
    assert grant not in repo.list_active()


@pytest.mark.asyncio
async def test_discover_new_skips_programs_already_in_catalog(tmp_path):
    repo = _repo(tmp_path)
    llm = _FakeLLM(responses=[
        {"programas": [{"nombre": "Kit Consulting", "criterios": "", "min_employees": None, "max_employees": None, "importe_desc": "", "url": "", "vigente_hasta": ""}]},
    ])
    brave = _FakeSearchClient()
    service = GrantsDiscoveryService(grants=repo, llm=llm, brave=brave)

    result = await service.discover_new(ambito="estatal", hints=["ayudas ia"])

    # el LLM devolvio "Kit Consulting" (ya en catalogo) — no debe duplicarse
    assert result["discovered"] == []
    assert len([g for g in repo.list_all() if g.slug == "kit_consulting"]) == 1


@pytest.mark.asyncio
async def test_discovery_falls_back_to_ddg_when_brave_disabled(tmp_path):
    repo = _repo(tmp_path)
    llm = _FakeLLM(responses=[{"programas": []}])
    brave = _FakeSearchClient(enabled=False)
    ddg = _FakeSearchClient()
    service = GrantsDiscoveryService(grants=repo, llm=llm, brave=brave, ddg=ddg)

    await service.discover_new(ambito="estatal", hints=["ayudas ia"])

    assert brave.calls == []
    assert len(ddg.calls) == 1
