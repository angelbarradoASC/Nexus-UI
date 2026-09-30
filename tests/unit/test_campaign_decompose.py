"""tests/unit/test_campaign_decompose.py

Tests unitarios para CampaignDecomposer — descomposición de una petición
de Campaña en lenguaje natural + verificación de ida y vuelta contra el
LLM local, vía similitud de embeddings (no una opinión del LLM sobre sí
mismo). Deliberadamente distinto del pipeline de Sales.
"""

from __future__ import annotations

import json

import pytest

from nexus.prospecting.campaign_decompose import SIMILARITY_THRESHOLD, CampaignDecomposer
from nexus.prospecting.regulations import RegulationsRepository
from nexus.prospecting.sales_verticals import SalesVerticalsRepository


class _FakeLLMResponse:
    def __init__(self, *, tool_calls=None, content=None, error=None):
        self.tool_calls = tool_calls
        self.content = content
        self.error = error


def _tool_call(call_id: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": "set_campaign_query", "arguments": json.dumps(arguments)}}


class _FakeLLMRouter:
    def __init__(self, responses: list[_FakeLLMResponse]):
        self._responses = list(responses)

    async def call(self, **kwargs):
        return self._responses.pop(0)


class _FakeLocalLLM:
    enabled = True

    def __init__(self, reconstruction: str | None = "peluquerías en Zaragoza en un radio de 12 km"):
        self._reconstruction = reconstruction
        self.calls: list[dict] = []

    async def complete(self, *, system_prompt: str, user_prompt: str, temperature=None, max_tokens=None):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._reconstruction


class _FakeEmbeddings:
    enabled = True

    def __init__(self, vectors: dict[str, list[float]]):
        # vectors keyed by exact text — el test controla que embedding devuelve cada texto
        self._vectors = vectors

    async def embed(self, text: str):
        return self._vectors.get(text)


def _verticals(tmp_path) -> SalesVerticalsRepository:
    return SalesVerticalsRepository(data_dir=tmp_path)


def _decomposer(tmp_path, *, llm_router, local_llm, embeddings, regulations=None) -> CampaignDecomposer:
    return CampaignDecomposer(
        llm_router=llm_router,
        local_llm=local_llm,
        embeddings=embeddings,
        verticals=_verticals(tmp_path),
        regulations=regulations,
    )


# ── Caso feliz: coincide, se marca consistente ──────────────────────────────

@pytest.mark.asyncio
async def test_consistent_when_reconstruction_matches_clean_intent(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="peluquerías", city="Zaragoza",
            radius_km=12, clean_intent="peluquerías en Zaragoza en un radio de 12 km",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction="peluquerías en Zaragoza en un radio de 12 km")
    embeddings = _FakeEmbeddings({
        "peluquerías en Zaragoza en un radio de 12 km": [1.0, 0.0, 0.0],
    })
    decomposer = _decomposer(tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings)

    result = await decomposer.decompose_and_verify(
        "quiero revisar salones de belleza o peluquerías en Zaragoza a 12 kilómetros"
    )

    assert result["status"] == "ok"
    assert result["query"]["business_type"] == "peluquerías"
    assert result["query"]["city"] == "Zaragoza"
    assert result["query"]["radius_km"] == 12
    assert result["similarity"] == pytest.approx(1.0)
    assert result["consistent"] is True
    assert result["threshold"] == SIMILARITY_THRESHOLD


@pytest.mark.asyncio
async def test_inconsistent_when_reconstruction_diverges(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="peluquerías", city="Zaragoza",
            clean_intent="peluquerías en Zaragoza",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction="restaurantes en Madrid")
    embeddings = _FakeEmbeddings({
        "peluquerías en Zaragoza": [1.0, 0.0, 0.0],
        "restaurantes en Madrid": [0.0, 1.0, 0.0],
    })
    decomposer = _decomposer(tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings)

    result = await decomposer.decompose_and_verify("busca peluquerías en Zaragoza")

    assert result["consistent"] is False
    assert result["similarity"] == pytest.approx(0.0)
    assert "desvió" in result["note"]


# ── Casos de degradacion — nunca se oculta que no se pudo verificar ────────

@pytest.mark.asyncio
async def test_no_tool_call_returns_error_status(tmp_path):
    llm_router = _FakeLLMRouter([_FakeLLMResponse(tool_calls=None, content="no puedo ayudar con eso")])
    decomposer = _decomposer(
        tmp_path, llm_router=llm_router, local_llm=_FakeLocalLLM(), embeddings=_FakeEmbeddings({}),
    )

    result = await decomposer.decompose_and_verify("algo raro")

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_empty_text_returns_error_without_calling_llm(tmp_path):
    llm_router = _FakeLLMRouter([])  # si se llamara, pop() en lista vacia -> IndexError
    decomposer = _decomposer(
        tmp_path, llm_router=llm_router, local_llm=_FakeLocalLLM(), embeddings=_FakeEmbeddings({}),
    )

    result = await decomposer.decompose_and_verify("   ")

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_local_llm_disabled_marks_unverified_but_keeps_decomposition(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="peluquerías", city="Zaragoza", clean_intent="peluquerías en Zaragoza",
        )]),
    ])
    local_llm = _FakeLocalLLM()
    local_llm.enabled = False
    decomposer = _decomposer(
        tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=_FakeEmbeddings({}),
    )

    result = await decomposer.decompose_and_verify("busca peluquerías en Zaragoza")

    assert result["status"] == "ok"
    assert result["query"]["business_type"] == "peluquerías"
    assert result["consistent"] is None
    assert result["similarity"] is None
    assert "no disponible" in result["note"]


@pytest.mark.asyncio
async def test_local_llm_no_response_marks_unverified(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="peluquerías", city="Zaragoza", clean_intent="peluquerías en Zaragoza",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction=None)
    embeddings = _FakeEmbeddings({"peluquerías en Zaragoza": [1.0, 0.0]})
    decomposer = _decomposer(tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings)

    result = await decomposer.decompose_and_verify("busca peluquerías en Zaragoza")

    assert result["consistent"] is None
    assert result["reconstructed"] is None
    assert "no respondió" in result["note"]


@pytest.mark.asyncio
async def test_missing_business_type_or_clean_intent_fails_decomposition(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", vertical="custom", city="Zaragoza")]),
    ])
    decomposer = _decomposer(
        tmp_path, llm_router=llm_router, local_llm=_FakeLocalLLM(), embeddings=_FakeEmbeddings({}),
    )

    result = await decomposer.decompose_and_verify("algo vago")

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_radius_km_omitted_when_not_mentioned(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="peluquerías", city="Zaragoza", clean_intent="peluquerías en Zaragoza",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction="peluquerías en Zaragoza")
    embeddings = _FakeEmbeddings({"peluquerías en Zaragoza": [1.0, 0.0]})
    decomposer = _decomposer(tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings)

    result = await decomposer.decompose_and_verify("busca peluquerías en Zaragoza")

    assert result["query"]["radius_km"] is None


# ── province / must_have — paridad con el brief de Sales ───────────────────

@pytest.mark.asyncio
async def test_province_and_must_have_are_extracted(tmp_path):
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="asesorias fiscales", city="Toledo",
            province="Toledo", must_have=["telefono"], clean_intent="asesorias fiscales en Toledo",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction="asesorias fiscales en Toledo")
    embeddings = _FakeEmbeddings({"asesorias fiscales en Toledo": [1.0, 0.0]})
    decomposer = _decomposer(tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings)

    result = await decomposer.decompose_and_verify("busca asesorias fiscales en Toledo, con telefono")

    assert result["query"]["province"] == "Toledo"
    assert result["query"]["must_have"] == ["telefono"]


# ── Criterio indirecto (normativa) — pedido explicito del usuario ──────────
# "quiero empresas afectadas por NIS2" no debe buscar el nombre literal de
# la ley (nadie se describe asi online) — debe usar los sectores REALES
# del catalogo, nunca lo que el LLM redacte por su cuenta.

@pytest.mark.asyncio
async def test_regulation_slug_grounds_business_type_in_real_sectors(tmp_path):
    regulations = RegulationsRepository(tmp_path)
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="empresas afectadas por la normativa NIS2",
            city="Zaragoza", province="Zaragoza", must_have=["telefono"], regulation_slug="nis2",
            clean_intent="empresas de Zaragoza afectadas por NIS2",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction="empresas de Zaragoza afectadas por NIS2")
    embeddings = _FakeEmbeddings({"empresas de Zaragoza afectadas por NIS2": [1.0, 0.0]})
    decomposer = _decomposer(
        tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings, regulations=regulations,
    )

    result = await decomposer.decompose_and_verify(
        "quiero empresas de la provincia de Zaragoza afectadas por la normativa NIS2, con telefono"
    )

    query = result["query"]
    assert query["regulation_slug"] == "nis2"
    assert "NIS2" not in query["business_type"]  # nunca el nombre literal de la ley
    assert "energía" in query["business_type"]  # sectores reales del catalogo
    assert query["must_have"] == ["telefono"]


@pytest.mark.asyncio
async def test_hallucinated_regulation_slug_is_discarded(tmp_path):
    """El LLM nunca puede colar una normativa que no exista de verdad en el
    catalogo — mismo guardarrail que ya usa la clasificacion de ayudas."""
    regulations = RegulationsRepository(tmp_path)
    llm_router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", vertical="custom", business_type="empresas afectadas por normativa inventada",
            city="Zaragoza", regulation_slug="normativa_que_no_existe",
            clean_intent="empresas afectadas por normativa inventada en Zaragoza",
        )]),
    ])
    local_llm = _FakeLocalLLM(reconstruction="empresas afectadas por normativa inventada en Zaragoza")
    embeddings = _FakeEmbeddings({"empresas afectadas por normativa inventada en Zaragoza": [1.0, 0.0]})
    decomposer = _decomposer(
        tmp_path, llm_router=llm_router, local_llm=local_llm, embeddings=embeddings, regulations=regulations,
    )

    result = await decomposer.decompose_and_verify("empresas afectadas por normativa inventada en Zaragoza")

    query = result["query"]
    assert "regulation_slug" not in query
    assert query["business_type"] == "empresas afectadas por normativa inventada"
