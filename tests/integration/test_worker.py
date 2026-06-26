"""
tests/integration/test_worker.py
-----------------------------------
Tests de integración para el Worker NEXUS-UI.

Cubre:
  - _procesar_tarea(): flujo feliz, chunks publicados, evento done
  - Manejo de errores: excepción en orchestrator, stream sin __done__
  - Formato del dict de resultado
  - Publicación Redis correcta (tipo/contenido de mensajes)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# El worker usa sys.path.insert(0, "/app") — replicar para tests
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_task(
    task_id="task-123",
    user_query="¿Cuánto es 2+2?",
    username="testuser",
    history=None,
    agent_override=None,
):
    return {
        "task_id":              task_id,
        "user_query":           user_query,
        "username":             username,
        "conversation_history": history or [],
        "agent_override":       agent_override,
        "timestamp":            "2026-04-07T10:00:00",
    }


async def _make_stream(*items):
    """Crea un async generator que emite los items dados."""
    for item in items:
        yield item


# ── Fixture de mock Redis ─────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.publish = AsyncMock(return_value=1)
    r.lpush   = AsyncMock(return_value=1)
    r.expire  = AsyncMock(return_value=True)
    return r


# ── Fixture de orchestrator mock ──────────────────────────────────────────────

@pytest.fixture
def mock_orchestrator():
    return MagicMock()


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — flujo feliz
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaFlujoFeliz:

    @pytest.mark.asyncio
    async def test_devuelve_dict_con_campos_obligatorios(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="Cuatro",
            intencion="general",
            confianza=0.95,
            agente_usado="GenerationAgent",
            exito=True,
        )

        async def _stream(*a, **kw):
            yield "Cu"
            yield "atro"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "worker"))
        from worker import _procesar_tarea

        result = await _procesar_tarea(
            mock_orchestrator, _make_task(), mock_redis
        )

        required = {"response", "thinking", "audit", "intencion", "confianza", "agente", "success"}
        assert required.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_resultado_exito_true(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="OK", intencion="general", confianza=0.9,
            agente_usado="Gen", exito=True,
        )

        async def _stream(*a, **kw):
            yield "OK"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_respuesta_incluida_en_resultado(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="La respuesta completa del agente",
            intencion="general", confianza=0.9, agente_usado="Gen", exito=True,
        )

        async def _stream(*a, **kw):
            yield "La respuesta "
            yield "completa del agente"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)
        assert result["response"] == "La respuesta completa del agente"


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — publicación Redis
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaPublicacionRedis:

    @pytest.mark.asyncio
    async def test_chunks_publicados_en_canal_correcto(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="R", intencion="general", confianza=0.9, agente_usado="G", exito=True,
        )

        async def _stream(*a, **kw):
            yield "chunk1"
            yield "chunk2"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(task_id="t-abc"), mock_redis)

        # Todos los publish al canal correcto
        for call in mock_redis.publish.call_args_list:
            canal = call.args[0]
            assert canal == "nexus_stream:t-abc"

    @pytest.mark.asyncio
    async def test_chunks_publicados_con_tipo_chunk(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="R", intencion="general", confianza=0.9, agente_usado="G", exito=True,
        )

        async def _stream(*a, **kw):
            yield "texto parcial"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        # El primer publish debe ser tipo "chunk"
        first_call = mock_redis.publish.call_args_list[0]
        data = json.loads(first_call.args[1])
        assert data["type"] == "chunk"
        assert data["content"] == "texto parcial"

    @pytest.mark.asyncio
    async def test_evento_done_publicado_al_final(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="R", intencion="general", confianza=0.9, agente_usado="G", exito=True,
        )

        async def _stream(*a, **kw):
            yield "chunk"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        # El último publish debe ser tipo "done"
        last_call = mock_redis.publish.call_args_list[-1]
        data = json.loads(last_call.args[1])
        assert data["type"] == "done"

    @pytest.mark.asyncio
    async def test_evento_done_incluye_agente_e_intencion(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="R", intencion="diagnostico_servidor", confianza=0.98,
            agente_usado="SSHAgent", exito=True,
        )

        async def _stream(*a, **kw):
            yield "output ssh"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        last_call = mock_redis.publish.call_args_list[-1]
        data = json.loads(last_call.args[1])
        assert data["agente"] == "SSHAgent"
        assert data["intencion"] == "diagnostico_servidor"
        assert data["success"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — manejo de errores
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaErrores:

    @pytest.mark.asyncio
    async def test_excepcion_en_stream_devuelve_resultado_error(self, mock_redis, mock_orchestrator):
        async def _stream(*a, **kw):
            yield "chunk"
            raise RuntimeError("LLM timeout")

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_excepcion_publica_evento_error_en_redis(self, mock_redis, mock_orchestrator):
        async def _stream(*a, **kw):
            raise ValueError("fallo total")
            yield  # Hace que sea un generator

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        # Debe haberse publicado un evento error
        error_published = False
        for call in mock_redis.publish.call_args_list:
            try:
                data = json.loads(call.args[1])
                if data.get("type") == "error":
                    error_published = True
                    break
            except Exception:
                pass
        assert error_published

    @pytest.mark.asyncio
    async def test_sin_evento_done_genera_excepcion_interna(self, mock_redis, mock_orchestrator):
        """Stream que cierra sin __done__ debe tratarse como error."""
        async def _stream(*a, **kw):
            yield "chunk"
            # No emite __done__

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_error_en_publish_redis_no_rompe_flujo(self, mock_orchestrator):
        """Si Redis falla al publicar, la tarea debe completarse de igual forma."""
        from agents.orchestration_agent import OrchestrationResult

        resultado = OrchestrationResult(
            respuesta="R", intencion="general", confianza=0.9, agente_usado="G", exito=True,
        )

        async def _stream(*a, **kw):
            yield "chunk"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        # Redis falla en todos los publish
        bad_redis = AsyncMock()
        bad_redis.publish = AsyncMock(side_effect=Exception("Redis down"))

        from worker import _procesar_tarea
        # No debe lanzar al caller del worker
        result = await _procesar_tarea(mock_orchestrator, _make_task(), bad_redis)
        # El resultado debe tener éxito aunque Redis fallara
        assert "success" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — extracción de campos del task_data
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaExtraccionDatos:

    @pytest.mark.asyncio
    async def test_agent_override_pasado_al_orchestrator(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult
        captured = {}

        async def _stream(user_query, username, history, agent_override=None):
            captured["agent_override"] = agent_override
            resultado = OrchestrationResult(
                respuesta="R", intencion="general", confianza=0.9,
                agente_usado="G", exito=True,
            )
            yield "R"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        from worker import _procesar_tarea
        task = _make_task(agent_override="analyst")
        await _procesar_tarea(mock_orchestrator, task, mock_redis)

        assert captured["agent_override"] == "analyst"

    @pytest.mark.asyncio
    async def test_historial_pasado_al_orchestrator(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult
        captured = {}

        async def _stream(user_query, username, history, agent_override=None):
            captured["history"] = history
            resultado = OrchestrationResult(
                respuesta="R", intencion="general", confianza=0.9,
                agente_usado="G", exito=True,
            )
            yield "R"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        historial = [{"role": "user", "content": "pregunta anterior"}]
        from worker import _procesar_tarea
        task = _make_task(history=historial)
        await _procesar_tarea(mock_orchestrator, task, mock_redis)

        assert captured["history"] == historial

    @pytest.mark.asyncio
    async def test_task_sin_history_usa_lista_vacia(self, mock_redis, mock_orchestrator):
        from agents.orchestration_agent import OrchestrationResult
        captured = {}

        async def _stream(user_query, username, history, agent_override=None):
            captured["history"] = history
            resultado = OrchestrationResult(
                respuesta="R", intencion="general", confianza=0.9,
                agente_usado="G", exito=True,
            )
            yield "R"
            yield {"__done__": True, "result": resultado}

        mock_orchestrator.process_query_stream = _stream

        # task_data sin conversation_history
        task = {"task_id": "t1", "user_query": "q", "username": "u"}
        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, task, mock_redis)

        assert captured["history"] == []
