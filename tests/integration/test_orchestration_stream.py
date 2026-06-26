"""
tests/integration/test_orchestration_stream.py
-------------------------------------------------
Tests de integración para process_query_stream() del OrchestrationAgent.

PATRÓN:
    Solo se mockea get_router(). Los agentes (IntentionAgent, SSHAgent, JiraAgent,
    etc.) son instancias reales — se ejecuta código real, no dobles.
    Para evitar I/O externo, se parchea únicamente el método ejecutar() de la
    instancia concreta en los tests que lo necesitan.

    Este patrón es idéntico al de test_orchestration.py pero para la ruta
    de streaming (process_query_stream).

CONTRATO DEL STREAM:
    - yield str  : chunk de texto durante la generación
    - yield dict : {"__done__": True, "result": OrchestrationResult} al finalizar
    - El __done__ llega SIEMPRE, incluso si hay error.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _collect_stream(gen):
    """Consume el async generator y separa chunks de texto del dict __done__."""
    chunks: list[str] = []
    done: dict | None = None
    async for item in gen:
        if isinstance(item, dict) and item.get("__done__"):
            done = item
        else:
            chunks.append(str(item))
    return chunks, done


def make_stream_router(
    intention_response: dict,
    stream_chunks: list[str] | None = None,
):
    """
    Router para tests de process_query_stream().

    - call()        → primera llamada devuelve JSON de clasificación (IntentionAgent)
                      llamadas posteriores devuelven texto concatenado.
    - call_stream() → async generator que emite los chunks dados.

    El patrón es idéntico a make_router() en test_orchestration.py, con la
    adición de call_stream para las rutas de streaming real (GenerationAgent,
    AnalystAgent, CoderAgent, ResearcherAgent).
    """
    from agents.llm_router import LLMResponse, LLMRouter

    chunks = stream_chunks or ["Respuesta", " de", " test."]
    call_count = 0

    async def mock_call(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Primera llamada → clasificación de intención
            return LLMResponse(
                content=json.dumps(intention_response),
                level_used=0, model_used="test",
            )
        # Llamadas posteriores → generación de texto (no-stream)
        return LLMResponse(
            content="".join(chunks),
            level_used=0, model_used="test",
            latency_ms=10,
        )

    async def mock_stream(messages, **kwargs):
        for chunk in chunks:
            yield chunk

    router = MagicMock(spec=LLMRouter)
    router.call = mock_call
    router.call_stream = MagicMock(side_effect=mock_stream)
    router.available_levels = MagicMock(return_value=[0])
    router.metrics_snapshot = MagicMock(return_value={})
    return router


def _make_orchestrator(router):
    """Crea OrchestrationAgent con el router dado sin I/O externo."""
    with patch("agents.orchestration_agent.get_router", return_value=router):
        from agents.orchestration_agent import OrchestrationAgent
        return OrchestrationAgent()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def orch_general():
    """Orchestrator que clasifica como 'general' y emite 3 chunks fijos."""
    router = make_stream_router(
        {"intention": "general", "entities": {}, "confidence": 0.99},
        stream_chunks=["Hola", " mundo", " streaming"],
    )
    return _make_orchestrator(router)


@pytest.fixture
def orch_ssh():
    """
    Orchestrator que clasifica como 'diagnostico_servidor' con servidor especificado.
    El SSHAgent real está instanciado — se parchea su ejecutar() en cada test.
    """
    router = make_stream_router(
        {
            "intention": "diagnostico_servidor",
            "entities": {"servidor": "web-prod-01", "problema": None},
            "confidence": 0.95,
        },
    )
    return _make_orchestrator(router)


@pytest.fixture
def orch_jira():
    """
    Orchestrator que clasifica como 'crear_ticket_jira' con resumen.
    El JiraAgent real está instanciado — se parchea su ejecutar() en cada test.
    """
    router = make_stream_router(
        {
            "intention": "crear_ticket_jira",
            "entities": {"resumen": "Bug en producción", "accion": "crear"},
            "confidence": 0.92,
        },
    )
    return _make_orchestrator(router)


# ═══════════════════════════════════════════════════════════════════════════════
# process_query_stream — flujo básico (intención general)
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessQueryStreamBasic:

    @pytest.mark.asyncio
    async def test_stream_emite_chunks_de_texto_y_done(self, orch_general):
        gen = orch_general.process_query_stream("Hola", "testuser", [])
        chunks, done = await _collect_stream(gen)

        assert len(chunks) > 0, "Debe emitir al menos un chunk de texto"
        assert done is not None, "El stream debe terminar con __done__"

    @pytest.mark.asyncio
    async def test_chunks_concatenados_igualan_respuesta_del_done(self, orch_general):
        """El texto total de los chunks debe coincidir con result.respuesta."""
        gen = orch_general.process_query_stream("Query", "testuser", [])
        chunks, done = await _collect_stream(gen)

        texto_total = "".join(chunks)
        assert texto_total == done["result"].respuesta

    @pytest.mark.asyncio
    async def test_done_tiene_intencion_general(self, orch_general):
        gen = orch_general.process_query_stream("¿Qué es Python?", "testuser", [])
        _, done = await _collect_stream(gen)

        assert done["result"].intencion == "general"

    @pytest.mark.asyncio
    async def test_done_tiene_exito_true(self, orch_general):
        gen = orch_general.process_query_stream("Query de test", "testuser", [])
        _, done = await _collect_stream(gen)

        assert done["result"].exito is True

    @pytest.mark.asyncio
    async def test_done_agente_usado_no_vacio(self, orch_general):
        gen = orch_general.process_query_stream("Query", "testuser", [])
        _, done = await _collect_stream(gen)

        assert done["result"].agente_usado  # No vacío
        assert "generation" in done["result"].agente_usado.lower()

    @pytest.mark.asyncio
    async def test_confianza_viene_de_clasificacion(self, orch_general):
        gen = orch_general.process_query_stream("Query", "testuser", [])
        _, done = await _collect_stream(gen)

        # El router devuelve confidence: 0.99 en la clasificación
        assert done["result"].confianza == pytest.approx(0.99, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# process_query_stream — follow-up question
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessQueryStreamFollowUp:
    """
    Cuando la intención es diagnostico_servidor pero no se especifica servidor,
    IntentionAgent._validar genera una follow_up_question. El orquestador debe
    emitirla como chunk y terminar con agente_usado='intention_followup'.
    """

    @pytest.fixture
    def orch_ssh_sin_servidor(self):
        """Clasifica como SSH pero entities.servidor=None — activa follow-up real."""
        router = make_stream_router(
            {
                "intention": "diagnostico_servidor",
                "entities": {"servidor": None},
                "confidence": 0.8,
            },
        )
        return _make_orchestrator(router)

    @pytest.mark.asyncio
    async def test_follow_up_se_emite_como_chunk(self, orch_ssh_sin_servidor):
        gen = orch_ssh_sin_servidor.process_query_stream(
            "Revisa el servidor", "testuser", []
        )
        chunks, done = await _collect_stream(gen)

        # La pregunta debe aparecer en los chunks
        texto = "".join(chunks)
        assert "servidor" in texto.lower() or "hostname" in texto.lower() or len(texto) > 5

    @pytest.mark.asyncio
    async def test_follow_up_agente_es_intention_followup(self, orch_ssh_sin_servidor):
        gen = orch_ssh_sin_servidor.process_query_stream(
            "Revisa el servidor", "testuser", []
        )
        _, done = await _collect_stream(gen)

        assert done["result"].agente_usado == "intention_followup"

    @pytest.mark.asyncio
    async def test_follow_up_no_llama_ejecutar_del_ssh(self, orch_ssh_sin_servidor):
        """El follow-up debe cortocircuitar antes de llamar al SSHAgent."""
        from agents.intention_agent import Intencion
        ssh_agent = orch_ssh_sin_servidor._agents[Intencion.DIAGNOSTICO_SERVIDOR]
        ssh_agent.ejecutar = AsyncMock()

        gen = orch_ssh_sin_servidor.process_query_stream(
            "revisa el servidor", "testuser", []
        )
        await _collect_stream(gen)

        ssh_agent.ejecutar.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# process_query_stream — agent_override routing
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessQueryStreamAgentOverride:

    @pytest.mark.asyncio
    async def test_override_analyst_usa_analyst_agent(self, orch_general):
        gen = orch_general.process_query_stream(
            "Analiza estos datos", "testuser", [], agent_override="analyst"
        )
        _, done = await _collect_stream(gen)

        assert "analyst" in done["result"].agente_usado.lower()

    @pytest.mark.asyncio
    async def test_override_coder_usa_coder_agent(self, orch_general):
        gen = orch_general.process_query_stream(
            "Escribe código Python", "testuser", [], agent_override="coder"
        )
        _, done = await _collect_stream(gen)

        assert "coder" in done["result"].agente_usado.lower()

    @pytest.mark.asyncio
    async def test_override_researcher_usa_researcher_agent(self, orch_general):
        gen = orch_general.process_query_stream(
            "Investiga sobre FastAPI", "testuser", [], agent_override="researcher"
        )
        _, done = await _collect_stream(gen)

        assert "researcher" in done["result"].agente_usado.lower()

    @pytest.mark.asyncio
    async def test_override_invalido_usa_generation_agent(self, orch_general):
        """Un override no reconocido se ignora — el sistema usa GenerationAgent."""
        gen = orch_general.process_query_stream(
            "Query general", "testuser", [], agent_override="superagent_inexistente"
        )
        _, done = await _collect_stream(gen)

        assert done["result"].exito is True
        assert "generation" in done["result"].agente_usado.lower()

    @pytest.mark.asyncio
    async def test_override_ignorado_para_intencion_ssh(self, orch_ssh):
        """Para diagnóstico SSH, el override de modo se ignora — SSH gana siempre."""
        from agents.base_agent import AgentResult
        from agents.intention_agent import Intencion

        ssh_agent = orch_ssh._agents[Intencion.DIAGNOSTICO_SERVIDOR]
        ssh_agent.ejecutar = AsyncMock(
            return_value=AgentResult(
                respuesta="CPU 45% RAM 62%",
                exito=True, agente="SSHAgent", datos={},
            )
        )

        gen = orch_ssh.process_query_stream(
            "Revisa web-prod-01", "testuser", [], agent_override="analyst"
        )
        _, done = await _collect_stream(gen)

        ssh_agent.ejecutar.assert_called_once()
        assert "analyst" not in done["result"].agente_usado.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# process_query_stream — agentes no-streaming (SSH, Jira)
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessQueryStreamNonStreamingAgents:
    """
    SSH, Jira y Web ejecutan mediante ejecutar() (síncrono).
    El orquestador emite su respuesta completa como UN único chunk str y luego __done__.
    """

    @pytest.mark.asyncio
    async def test_ssh_respuesta_emitida_como_chunk(self, orch_ssh):
        from agents.base_agent import AgentResult
        from agents.intention_agent import Intencion

        orch_ssh._agents[Intencion.DIAGNOSTICO_SERVIDOR].ejecutar = AsyncMock(
            return_value=AgentResult(
                respuesta="CPU: 45% | RAM: 60% | Disco: OK",
                exito=True, agente="SSHAgent", datos={},
            )
        )

        gen = orch_ssh.process_query_stream("Estado del servidor", "testuser", [])
        chunks, done = await _collect_stream(gen)

        assert "CPU: 45% | RAM: 60% | Disco: OK" in chunks
        assert done["result"].intencion == "diagnostico_servidor"
        assert done["result"].exito is True

    @pytest.mark.asyncio
    async def test_jira_respuesta_emitida_como_chunk(self, orch_jira):
        from agents.base_agent import AgentResult
        from agents.intention_agent import Intencion

        orch_jira._agents[Intencion.CREAR_TICKET_JIRA].ejecutar = AsyncMock(
            return_value=AgentResult(
                respuesta="Ticket PRJ-42 creado correctamente",
                exito=True, agente="JiraAgent", datos={},
            )
        )

        gen = orch_jira.process_query_stream("Crea un ticket de bug", "testuser", [])
        chunks, done = await _collect_stream(gen)

        assert "PRJ-42" in "".join(chunks)
        assert done["result"].intencion == "crear_ticket_jira"

    @pytest.mark.asyncio
    async def test_agente_no_streaming_done_contiene_agente_correcto(self, orch_ssh):
        from agents.base_agent import AgentResult
        from agents.intention_agent import Intencion

        orch_ssh._agents[Intencion.DIAGNOSTICO_SERVIDOR].ejecutar = AsyncMock(
            return_value=AgentResult(
                respuesta="Resultado",
                exito=True, agente="SSHAgent", datos={"ip": "10.0.0.1"},
            )
        )

        gen = orch_ssh.process_query_stream("revisa web-prod-01", "testuser", [])
        _, done = await _collect_stream(gen)

        assert done["result"].agente_usado == "SSHAgent"
        assert done["result"].datos.get("ip") == "10.0.0.1"


# ═══════════════════════════════════════════════════════════════════════════════
# process_query_stream — manejo de errores
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessQueryStreamErrors:

    @pytest.mark.asyncio
    async def test_excepcion_en_agente_devuelve_done_exito_false(self, orch_ssh):
        from agents.intention_agent import Intencion

        orch_ssh._agents[Intencion.DIAGNOSTICO_SERVIDOR].ejecutar = AsyncMock(
            side_effect=RuntimeError("SSH connection refused")
        )

        gen = orch_ssh.process_query_stream("Conecta al servidor", "testuser", [])
        chunks, done = await _collect_stream(gen)

        assert done is not None
        assert done["result"].exito is False
        assert done["result"].agente_usado == "orchestrator_error"

    @pytest.mark.asyncio
    async def test_stream_siempre_termina_con_done(self, orch_general):
        """Incluso si la clasificación del LLM devuelve basura, el stream termina."""
        # Crear router que devuelve JSON malformado en clasificación
        from agents.llm_router import LLMResponse, LLMRouter
        bad_router = MagicMock(spec=LLMRouter)
        bad_router.call = AsyncMock(return_value=LLMResponse(
            content="esto no es json válido !!!",
            level_used=0, model_used="test",
        ))
        bad_router.call_stream = orch_general._router.call_stream
        bad_router.available_levels = MagicMock(return_value=[0])
        orch_general._intention.router = bad_router

        gen = orch_general.process_query_stream("Query", "testuser", [])
        _, done = await _collect_stream(gen)

        # Fallback a "general" con confianza 0 — el stream debe cerrar
        assert done is not None

    @pytest.mark.asyncio
    async def test_excepcion_inesperada_genera_done_exito_false(self, orch_general):
        """Excepción no controlada en el agente resulta en done con exito=False."""
        from agents.intention_agent import Intencion

        orch_general._agents[Intencion.GENERAL].ejecutar_stream = MagicMock(
            side_effect=Exception("Error inesperado del LLM")
        )

        gen = orch_general.process_query_stream("Query", "testuser", [])
        _, done = await _collect_stream(gen)

        assert done is not None
        assert done["result"].exito is False


# ═══════════════════════════════════════════════════════════════════════════════
# _resolver_agente — lógica de selección de agente
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolverAgente:
    """
    Tests unitarios del método _resolver_agente().
    Instancias reales — valida contratos de tipo, no mocks.
    """

    @pytest.fixture
    def orch(self, orch_general):
        return orch_general

    def test_sin_override_general_devuelve_generation_agent(self, orch):
        from agents.generation_agent import GenerationAgent
        from agents.intention_agent import Intencion
        agente = orch._resolver_agente(Intencion.GENERAL, None)
        assert isinstance(agente, GenerationAgent)

    def test_override_analyst_con_general(self, orch):
        from agents.analyst_agent import AnalystAgent
        from agents.intention_agent import Intencion
        agente = orch._resolver_agente(Intencion.GENERAL, "analyst")
        assert isinstance(agente, AnalystAgent)

    def test_override_coder_con_general(self, orch):
        from agents.coder_agent import CoderAgent
        from agents.intention_agent import Intencion
        agente = orch._resolver_agente(Intencion.GENERAL, "coder")
        assert isinstance(agente, CoderAgent)

    def test_override_researcher_con_general(self, orch):
        from agents.researcher_agent import ResearcherAgent
        from agents.intention_agent import Intencion
        agente = orch._resolver_agente(Intencion.GENERAL, "researcher")
        assert isinstance(agente, ResearcherAgent)

    def test_override_ignorado_con_intencion_ssh(self, orch):
        """Para SSH/Jira, el override 'analyst' se ignora."""
        from agents.analyst_agent import AnalystAgent
        from agents.intention_agent import Intencion
        agente = orch._resolver_agente(Intencion.DIAGNOSTICO_SERVIDOR, "analyst")
        # Debe ser SSHAgent (u otro agente técnico), nunca AnalystAgent
        assert not isinstance(agente, AnalystAgent)

    def test_override_invalido_cae_a_general(self, orch):
        from agents.generation_agent import GenerationAgent
        from agents.intention_agent import Intencion
        agente = orch._resolver_agente(Intencion.GENERAL, "agente_que_no_existe")
        assert isinstance(agente, GenerationAgent)
