"""
tests/unit/test_intention_agent.py
------------------------------------
Tests unitarios para app/agents/intention_agent.py.
Mockea LLMRouter para no necesitar LLM real.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


def make_llm_router_with_response(json_response: dict) -> MagicMock:
    """Helper: router que devuelve un JSON de clasificación."""
    from agents.llm_router import LLMResponse, LLMRouter
    router = MagicMock(spec=LLMRouter)
    router.call = AsyncMock(return_value=LLMResponse(
        content=json.dumps(json_response),
        level_used=0,
        model_used="test-model",
    ))
    return router


@pytest.fixture
def agent(mock_llm_router):
    from agents.intention_agent import IntentionAgent
    return IntentionAgent(mock_llm_router)


class TestClasificacion:
    @pytest.mark.asyncio
    async def test_clasifica_diagnostico_servidor(self):
        router = make_llm_router_with_response({
            "intention": "diagnostico_servidor",
            "entities": {"servidor": "web-prod-01", "problema": None},
            "confidence": 0.95,
        })
        from agents.intention_agent import IntentionAgent, Intencion
        agent = IntentionAgent(router)
        result = await agent.classify("revisa el servidor web-prod-01")
        assert result.intention == Intencion.DIAGNOSTICO_SERVIDOR
        assert result.entities["servidor"] == "web-prod-01"
        assert result.confidence == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_clasifica_crear_ticket_jira(self):
        router = make_llm_router_with_response({
            "intention": "crear_ticket_jira",
            "entities": {
                "resumen": "Servicio caído",
                "accion": "crear",
                "tipo_ticket": "Bug",
            },
            "confidence": 0.92,
        })
        from agents.intention_agent import IntentionAgent, Intencion
        agent = IntentionAgent(router)
        result = await agent.classify("crea un ticket: el servicio está caído")
        assert result.intention == Intencion.CREAR_TICKET_JIRA

    @pytest.mark.asyncio
    async def test_clasifica_busqueda_web(self):
        router = make_llm_router_with_response({
            "intention": "busqueda_web",
            "entities": {"search_query": "precio bitcoin hoy"},
            "confidence": 0.98,
        })
        from agents.intention_agent import IntentionAgent, Intencion
        agent = IntentionAgent(router)
        result = await agent.classify("busca el precio del bitcoin")
        assert result.intention == Intencion.BUSQUEDA_WEB

    @pytest.mark.asyncio
    async def test_clasifica_general(self, agent):
        from agents.llm_router import LLMResponse
        agent.router.call = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "intention": "general",
                "entities": {},
                "confidence": 0.99,
            }),
            level_used=0, model_used="test",
        ))
        from agents.intention_agent import Intencion
        result = await agent.classify("hola, ¿cómo estás?")
        assert result.intention == Intencion.GENERAL


class TestFallbacks:
    @pytest.mark.asyncio
    async def test_fallback_si_llm_error(self):
        from agents.llm_router import LLMResponse, LLMRouter
        router = MagicMock(spec=LLMRouter)
        router.call = AsyncMock(return_value=LLMResponse(
            content="", level_used=-1, model_used="none",
            error="timeout | nivel=L0 | 5000ms",
        ))
        from agents.intention_agent import IntentionAgent, Intencion
        agent = IntentionAgent(router)
        result = await agent.classify("cualquier cosa")
        assert result.intention == Intencion.GENERAL
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_fallback_si_json_invalido(self):
        from agents.llm_router import LLMResponse, LLMRouter
        router = MagicMock(spec=LLMRouter)
        router.call = AsyncMock(return_value=LLMResponse(
            content="esto no es json válido",
            level_used=0, model_used="test",
        ))
        from agents.intention_agent import IntentionAgent, Intencion
        agent = IntentionAgent(router)
        result = await agent.classify("algo")
        assert result.intention == Intencion.GENERAL

    @pytest.mark.asyncio
    async def test_intencion_desconocida_usa_general(self):
        router = make_llm_router_with_response({
            "intention": "intencion_inexistente",
            "entities": {},
            "confidence": 0.5,
        })
        from agents.intention_agent import IntentionAgent, Intencion
        agent = IntentionAgent(router)
        result = await agent.classify("algo raro")
        assert result.intention == Intencion.GENERAL


class TestValidacion:
    @pytest.mark.asyncio
    async def test_follow_up_si_falta_servidor(self):
        router = make_llm_router_with_response({
            "intention": "diagnostico_servidor",
            "entities": {"servidor": None},
            "confidence": 0.8,
        })
        from agents.intention_agent import IntentionAgent
        agent = IntentionAgent(router)
        result = await agent.classify("revisa el servidor")
        assert result.follow_up_question is not None
        assert "servidor" in result.follow_up_question.lower()

    @pytest.mark.asyncio
    async def test_follow_up_si_falta_resumen_ticket(self):
        router = make_llm_router_with_response({
            "intention": "crear_ticket_jira",
            "entities": {"accion": "crear", "resumen": None},
            "confidence": 0.8,
        })
        from agents.intention_agent import IntentionAgent
        agent = IntentionAgent(router)
        result = await agent.classify("crea un ticket")
        assert result.follow_up_question is not None

    @pytest.mark.asyncio
    async def test_no_follow_up_si_datos_completos(self):
        router = make_llm_router_with_response({
            "intention": "diagnostico_servidor",
            "entities": {"servidor": "web-01"},
            "confidence": 0.95,
        })
        from agents.intention_agent import IntentionAgent
        agent = IntentionAgent(router)
        result = await agent.classify("revisa web-01")
        assert result.follow_up_question is None


class TestParsearJson:
    def test_json_directo(self):
        from agents.intention_agent import IntentionAgent
        result = IntentionAgent._parsear_json('{"intention": "general", "confidence": 0.9}')
        assert result["intention"] == "general"

    def test_json_en_bloque_markdown(self):
        from agents.intention_agent import IntentionAgent
        texto = '```json\n{"intention": "general"}\n```'
        result = IntentionAgent._parsear_json(texto)
        assert result["intention"] == "general"

    def test_json_con_texto_alrededor(self):
        from agents.intention_agent import IntentionAgent
        texto = 'Aquí está el resultado: {"intention": "general"} como puedes ver.'
        result = IntentionAgent._parsear_json(texto)
        assert result["intention"] == "general"

    def test_json_invalido_lanza_error(self):
        from agents.intention_agent import IntentionAgent
        with pytest.raises(json.JSONDecodeError):
            IntentionAgent._parsear_json("esto no es json en absoluto")
