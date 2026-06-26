"""
tests/unit/test_mode_agents.py
--------------------------------
Tests unitarios para AnalystAgent, CoderAgent y ResearcherAgent.

Todos los tests mockean LLMRouter para no necesitar LLM real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture
def llm_response_ok():
    """LLMResponse de éxito estándar."""
    from agents.llm_router import LLMResponse
    return LLMResponse(
        content="Respuesta de test del modo agente.",
        level_used=0,
        model_used="test-model",
        nivel_name="L0-Test",
        latency_ms=10,
    )


@pytest.fixture
def llm_response_error():
    """LLMResponse de error."""
    from agents.llm_router import LLMResponse
    return LLMResponse(
        content="",
        level_used=-1,
        model_used="none",
        error="timeout | nivel=L0 | 5000ms",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AnalystAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalystAgent:
    """Tests para AnalystAgent."""

    @pytest.mark.asyncio
    async def test_ejecutar_devuelve_resultado_exito(self, mock_llm_router, llm_response_ok):
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router)
        result = await agent.ejecutar("Analiza estas métricas", {}, [])
        assert result.exito is True
        assert result.respuesta  # No vacío
        assert result.agente     # Nombre del agente

    @pytest.mark.asyncio
    async def test_ejecutar_usa_temperatura_baja(self, mock_llm_router, llm_response_ok):
        """AnalystAgent debe llamar al LLM con temperature=0.4 (más determinista)."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router)
        await agent.ejecutar("Dame estadísticas", {}, [])
        call_kwargs = mock_llm_router.call.call_args.kwargs
        assert call_kwargs.get("temperature") == 0.4

    @pytest.mark.asyncio
    async def test_ejecutar_con_historial_pasa_mensajes(self, mock_llm_router, llm_response_ok):
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router)
        historial = [
            {"role": "user", "content": "Pregunta anterior"},
            {"role": "assistant", "content": "Respuesta anterior"},
        ]
        await agent.ejecutar("Nueva consulta de análisis", {}, historial)
        messages = mock_llm_router.call.call_args.args[0]
        # El system prompt + historial + user query
        assert len(messages) >= 3
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_ejecutar_con_error_llm_devuelve_fallo(self, mock_llm_router, llm_response_error):
        mock_llm_router.call = AsyncMock(return_value=llm_response_error)
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router)
        result = await agent.ejecutar("Analiza", {}, [])
        assert result.exito is False
        assert result.respuesta  # Mensaje de error amigable

    @pytest.mark.asyncio
    async def test_ejecutar_stream_emite_chunks(self, mock_llm_router_stream):
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router_stream)
        chunks = []
        async for chunk in agent.ejecutar_stream("Analiza tendencias", []):
            chunks.append(chunk)
        assert len(chunks) == 3
        assert "".join(chunks) == "Hola mundo streaming"

    @pytest.mark.asyncio
    async def test_system_prompt_orientado_a_analisis(self, mock_llm_router, llm_response_ok):
        """El system prompt debe mencionar análisis/analista."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router)
        await agent.ejecutar("consulta", {}, [])
        messages = mock_llm_router.call.call_args.args[0]
        system_content = messages[0]["content"].lower()
        assert any(kw in system_content for kw in ["anali", "datos", "métricas"])


# ═══════════════════════════════════════════════════════════════════════════════
# CoderAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoderAgent:
    """Tests para CoderAgent."""

    @pytest.mark.asyncio
    async def test_ejecutar_devuelve_resultado_exito(self, mock_llm_router, llm_response_ok):
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router)
        result = await agent.ejecutar("Escribe un hello world en Python", {}, [])
        assert result.exito is True
        assert result.respuesta

    @pytest.mark.asyncio
    async def test_ejecutar_usa_temperatura_muy_baja(self, mock_llm_router, llm_response_ok):
        """CoderAgent debe llamar con temperature=0.2 (código preciso y reproducible)."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router)
        await agent.ejecutar("Implementa una función", {}, [])
        call_kwargs = mock_llm_router.call.call_args.kwargs
        assert call_kwargs.get("temperature") == 0.2

    @pytest.mark.asyncio
    async def test_ejecutar_usa_max_tokens_alto(self, mock_llm_router, llm_response_ok):
        """CoderAgent usa max_tokens=3000 para bloques de código completos."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router)
        await agent.ejecutar("Implementa una API REST completa", {}, [])
        call_kwargs = mock_llm_router.call.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 3000

    @pytest.mark.asyncio
    async def test_ejecutar_con_error_llm_devuelve_fallo(self, mock_llm_router, llm_response_error):
        mock_llm_router.call = AsyncMock(return_value=llm_response_error)
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router)
        result = await agent.ejecutar("Dame código", {}, [])
        assert result.exito is False

    @pytest.mark.asyncio
    async def test_ejecutar_stream_emite_chunks(self, mock_llm_router_stream):
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router_stream)
        chunks = []
        async for chunk in agent.ejecutar_stream("Crea una función", []):
            chunks.append(chunk)
        assert len(chunks) > 0
        assert "".join(chunks)

    @pytest.mark.asyncio
    async def test_system_prompt_orientado_a_codigo(self, mock_llm_router, llm_response_ok):
        """El system prompt debe mencionar código/ingeniería."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router)
        await agent.ejecutar("query", {}, [])
        messages = mock_llm_router.call.call_args.args[0]
        system_content = messages[0]["content"].lower()
        assert any(kw in system_content for kw in ["código", "coder", "codigo", "refactor"])


# ═══════════════════════════════════════════════════════════════════════════════
# ResearcherAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearcherAgent:
    """Tests para ResearcherAgent."""

    @pytest.mark.asyncio
    async def test_ejecutar_devuelve_resultado_exito(self, mock_llm_router, llm_response_ok):
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent()
        agent.router = mock_llm_router
        result = await agent.ejecutar("Investiga sobre Python", {}, [])
        assert result.exito is True
        assert result.respuesta

    @pytest.mark.asyncio
    async def test_ejecutar_sin_web_agent_funciona(self, mock_llm_router, llm_response_ok):
        """Sin web_agent inyectado, el agente debe funcionar como GenerationAgent."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent(web_agent=None)
        agent.router = mock_llm_router
        result = await agent.ejecutar("Investiga sobre async Python", {}, [])
        assert result.exito is True

    @pytest.mark.asyncio
    async def test_ejecutar_con_web_no_necesario_no_llama_web(
        self, mock_llm_router, llm_response_ok
    ):
        """Para consultas sin keywords de tiempo real, web_agent no se llama."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        mock_web_agent = AsyncMock()
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent(web_agent=mock_web_agent)
        agent.router = mock_llm_router
        # Consulta sin keywords "hoy", "noticias", "precio"...
        await agent.ejecutar("Explícame el algoritmo quicksort", {}, [])
        mock_web_agent.ejecutar.assert_not_called()

    @pytest.mark.asyncio
    async def test_ejecutar_con_web_necesario_llama_web(
        self, mock_llm_router, llm_response_ok
    ):
        """Para consultas con keywords actuales, web_agent debe ser consultado."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.base_agent import AgentResult
        mock_web_result = AgentResult(
            respuesta="Noticias actuales de Python",
            exito=True,
            agente="web_agent",
        )
        mock_web_agent = MagicMock()
        mock_web_agent.ejecutar = AsyncMock(return_value=mock_web_result)
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent(web_agent=mock_web_agent)
        agent.router = mock_llm_router
        # Consulta con keyword de actualidad
        await agent.ejecutar("noticias recientes sobre Python hoy", {}, [])
        mock_web_agent.ejecutar.assert_called_once()

    @pytest.mark.asyncio
    async def test_ejecutar_web_falla_continua_sin_contexto(
        self, mock_llm_router, llm_response_ok
    ):
        """Si web_agent falla, el investigador continúa sin contexto web."""
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        mock_web_agent = MagicMock()
        mock_web_agent.ejecutar = AsyncMock(side_effect=Exception("Web timeout"))
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent(web_agent=mock_web_agent)
        agent.router = mock_llm_router
        # No debe lanzar excepción
        result = await agent.ejecutar("últimas noticias Python", {}, [])
        assert result.exito is True

    @pytest.mark.asyncio
    async def test_ejecutar_stream_emite_chunks(self, mock_llm_router_stream):
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent(web_agent=None)
        agent.router = mock_llm_router_stream
        chunks = []
        async for chunk in agent.ejecutar_stream("Investiga arquitecturas", []):
            chunks.append(chunk)
        assert len(chunks) > 0

    @pytest.mark.parametrize("consulta,esperado", [
        ("¿Cuál es el precio de Bitcoin hoy?", True),
        ("últimas noticias de tecnología", True),
        ("estado actual del servidor", True),
        ("versión más reciente de FastAPI", True),
        ("¿Cómo funciona el algoritmo de Dijkstra?", False),
        ("Explícame los principios SOLID", False),
        ("¿Qué es un decorador en Python?", False),
    ])
    def test_necesita_web_heuristica(self, consulta, esperado):
        from agents.researcher_agent import ResearcherAgent
        assert ResearcherAgent._necesita_web(consulta) == esperado

    @pytest.mark.asyncio
    async def test_system_prompt_orientado_a_investigacion(
        self, mock_llm_router, llm_response_ok
    ):
        mock_llm_router.call = AsyncMock(return_value=llm_response_ok)
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent()
        agent.router = mock_llm_router
        await agent.ejecutar("query", {}, [])
        messages = mock_llm_router.call.call_args.args[0]
        system_content = messages[0]["content"].lower()
        assert any(kw in system_content for kw in ["investig", "researcher", "informe"])


# ═══════════════════════════════════════════════════════════════════════════════
# Comprobación de herencia y nombres
# ═══════════════════════════════════════════════════════════════════════════════

class TestModeAgentInheritance:
    """Verifica que los agentes de modo heredan de GenerationAgent."""

    def test_analyst_es_generation_agent(self):
        from agents.analyst_agent import AnalystAgent
        from agents.generation_agent import GenerationAgent
        assert issubclass(AnalystAgent, GenerationAgent)

    def test_coder_es_generation_agent(self):
        from agents.coder_agent import CoderAgent
        from agents.generation_agent import GenerationAgent
        assert issubclass(CoderAgent, GenerationAgent)

    def test_researcher_es_generation_agent(self):
        from agents.researcher_agent import ResearcherAgent
        from agents.generation_agent import GenerationAgent
        assert issubclass(ResearcherAgent, GenerationAgent)

    def test_analyst_nombre(self, mock_llm_router):
        from agents.analyst_agent import AnalystAgent
        agent = AnalystAgent(router=mock_llm_router)
        assert agent._nombre()  # No vacío

    def test_coder_nombre(self, mock_llm_router):
        from agents.coder_agent import CoderAgent
        agent = CoderAgent(router=mock_llm_router)
        assert agent._nombre()

    def test_researcher_nombre(self):
        from agents.researcher_agent import ResearcherAgent
        agent = ResearcherAgent()
        assert agent._nombre()
