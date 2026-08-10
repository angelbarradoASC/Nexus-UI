"""
tests/integration/test_worker.py
-----------------------------------
Tests de integración para el Worker NEXUS-UI.

Cubre _procesar_tarea(): flujo feliz, chunks publicados, evento done,
manejo de errores, formato del dict de resultado, publicación Redis.

NOTA IMPORTANTE (auditoria de tests, sin tocar codigo de produccion):
worker.py._procesar_tarea llama a `orchestrator.process(user_query)` (un
unico positional arg — no pasa conversation_history ni agent_override pese
a que task_data los trae) y espera un objeto con atributos en ingles:
`.success`, `.response`, `.intent`, `.routing_trace`, `.error`,
`.stream_chunks`. El modelo real `OrchestrationResult`
(app/agents/orchestration_agent.py) NO tiene esos campos — tiene
`.exito`, `.respuesta`, `.intencion`, `.confianza`, `.agente_usado`,
`.datos`. Cualquier llamada real cae en el `except Exception` amplio de
_procesar_tarea y devuelve success=False con un AttributeError como
mensaje de error — el worker no crashea, pero NUNCA tiene exito con un
orchestrator real. Ver test_orchestrator_result_real_no_encaja_con_worker
mas abajo, que fija (pinnea) este comportamiento actual explicitamente.
Esto es un bug de aplicacion, no de estos tests — no se toca worker.py
en esta pasada porque el encargo es solo arreglar los tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# El worker usa sys.path.insert(0, "/app") — replicar para tests
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "worker"))


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


def _fake_result(
    *,
    success=True,
    response="",
    intent=None,
    routing_trace=None,
    error=None,
    stream_chunks=None,
):
    """Doble de OrchestrationResult con los atributos que _procesar_tarea
    LEE REALMENTE hoy (.success/.response/.intent/.routing_trace/.error/
    .stream_chunks) — deliberadamente distinto del modelo Pydantic real,
    que usa otros nombres (ver nota del modulo).
    """
    return SimpleNamespace(
        success=success,
        response=response,
        intent=intent,
        routing_trace=routing_trace or [],
        error=error,
        stream_chunks=stream_chunks or [],
    )


# ── Fixture de mock Redis ─────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.publish = AsyncMock(return_value=1)
    r.lpush   = AsyncMock(return_value=1)
    r.expire  = AsyncMock(return_value=True)
    return r


# ── Fixture de orchestrator mock ──────────────────────────────────────────────
# AsyncMock, no MagicMock — _procesar_tarea hace `await orchestrator.process(...)`
# y un MagicMock normal no es "awaitable" (TypeError: object MagicMock can't be
# used in 'await' expression).

@pytest.fixture
def mock_orchestrator():
    return AsyncMock()


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — flujo feliz
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaFlujoFeliz:

    @pytest.mark.asyncio
    async def test_devuelve_dict_con_campos_obligatorios(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(return_value=_fake_result(response="Cuatro", success=True))

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        required = {"success", "response", "intent", "routing_trace", "error"}
        assert required.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_resultado_exito_true(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(return_value=_fake_result(response="OK", success=True))

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_respuesta_incluida_en_resultado(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(
            return_value=_fake_result(response="La respuesta completa del agente", success=True)
        )

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)
        assert result["response"] == "La respuesta completa del agente"


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — publicación Redis
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaPublicacionRedis:

    @pytest.mark.asyncio
    async def test_chunks_publicados_en_canal_correcto(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(
            return_value=_fake_result(success=True, stream_chunks=["chunk1", "chunk2"])
        )

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(task_id="t-abc"), mock_redis)

        # Canal real: f"nexus_stream_{task_id}" (guion bajo, no ":")
        for call in mock_redis.publish.call_args_list:
            canal = call.args[0]
            assert canal == "nexus_stream_t-abc"

    @pytest.mark.asyncio
    async def test_chunks_publicados_con_tipo_chunk(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(
            return_value=_fake_result(success=True, stream_chunks=["texto parcial"])
        )

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        # El primer publish debe ser tipo "chunk"
        first_call = mock_redis.publish.call_args_list[0]
        data = json.loads(first_call.args[1])
        assert data["type"] == "chunk"
        assert data["content"] == "texto parcial"

    @pytest.mark.asyncio
    async def test_evento_done_publicado_al_final(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(
            return_value=_fake_result(success=True, stream_chunks=["chunk"])
        )

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        # El último publish debe ser tipo "done"
        last_call = mock_redis.publish.call_args_list[-1]
        data = json.loads(last_call.args[1])
        assert data["type"] == "done"

    @pytest.mark.asyncio
    async def test_evento_done_incluye_intent_y_success(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(
            return_value=_fake_result(
                success=True, intent="diagnostico_servidor", stream_chunks=["output ssh"]
            )
        )

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        last_call = mock_redis.publish.call_args_list[-1]
        data = json.loads(last_call.args[1])
        # El "content" del evento done es el final_payload completo
        assert data["content"]["intent"] == "diagnostico_servidor"
        assert data["content"]["success"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — manejo de errores
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaErrores:

    @pytest.mark.asyncio
    async def test_excepcion_en_process_devuelve_resultado_error(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        assert result["success"] is False
        assert "error" in result
        assert "LLM timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_excepcion_publica_evento_error_en_redis(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(side_effect=ValueError("fallo total"))

        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

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
    async def test_redis_totalmente_caido_propaga_excepcion(self, mock_orchestrator):
        """Si TODOS los publish a Redis fallan, _procesar_tarea SI propaga la
        excepcion al caller: el primer fallo (durante el publish de un chunk)
        entra en el except, que intenta publicar un evento "error" con el
        mismo `redis` roto — esa segunda llamada tambien falla, y como esta
        fuera de cualquier try/except, se propaga sin capturar. No hay
        proteccion real contra una caida total de Redis (solo funcionaria si
        Redis fallase en el publish de chunks pero se recuperase a tiempo
        para el publish de done/error, algo que este mock no representa).
        """
        mock_orchestrator.process = AsyncMock(
            return_value=_fake_result(success=True, stream_chunks=["chunk"])
        )

        # Redis falla en todos los publish
        bad_redis = AsyncMock()
        bad_redis.publish = AsyncMock(side_effect=Exception("Redis down"))

        from worker import _procesar_tarea
        with pytest.raises(Exception, match="Redis down"):
            await _procesar_tarea(mock_orchestrator, _make_task(), bad_redis)


# ═══════════════════════════════════════════════════════════════════════════════
# _procesar_tarea — extracción de campos del task_data
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcesarTareaExtraccionDatos:
    """_procesar_tarea hoy SOLO lee task_id y user_query de task_data — NO pasa
    conversation_history ni agent_override al orchestrator (aunque _make_task()
    los incluye en el payload). Estos tests fijan ese comportamiento actual —
    si algun dia se recupera el paso de historial/agent_override habria que
    actualizarlos, pero no es este el momento de tocar worker.py.
    """

    @pytest.mark.asyncio
    async def test_process_se_llama_solo_con_user_query(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(return_value=_fake_result(success=True))

        from worker import _procesar_tarea
        task = _make_task(user_query="cuanto es 2+2", agent_override="analyst")
        await _procesar_tarea(mock_orchestrator, task, mock_redis)

        mock_orchestrator.process.assert_awaited_once_with("cuanto es 2+2")

    @pytest.mark.asyncio
    async def test_historial_y_agent_override_no_se_propagan(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(return_value=_fake_result(success=True))

        from worker import _procesar_tarea
        historial = [{"role": "user", "content": "pregunta anterior"}]
        task = _make_task(history=historial, agent_override="analyst")
        await _procesar_tarea(mock_orchestrator, task, mock_redis)

        # Un solo arg posicional: ni historial ni agent_override llegan al orchestrator.
        args, kwargs = mock_orchestrator.process.call_args
        assert len(args) == 1
        assert kwargs == {}

    @pytest.mark.asyncio
    async def test_task_sin_task_id_usa_unknown(self, mock_redis, mock_orchestrator):
        mock_orchestrator.process = AsyncMock(return_value=_fake_result(success=True))

        task = {"user_query": "q", "username": "u"}
        from worker import _procesar_tarea
        await _procesar_tarea(mock_orchestrator, task, mock_redis)

        last_call = mock_redis.publish.call_args_list[-1]
        assert last_call.args[0] == "nexus_stream_unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# Bug real documentado: OrchestrationResult (modelo Pydantic real) no encaja
# con los atributos que _procesar_tarea espera leer — ver nota de modulo.
# ═══════════════════════════════════════════════════════════════════════════════

class TestContratoRealOrchestrationResult:

    @pytest.mark.asyncio
    async def test_orchestrator_result_real_no_encaja_con_worker(self, mock_redis, mock_orchestrator):
        """Fija el comportamiento actual con un OrchestrationResult REAL (no un
        SimpleNamespace de conveniencia): worker.py accede a result.success,
        que OrchestrationResult no tiene (tiene result.exito) — el AttributeError
        cae en el except amplio de _procesar_tarea y el resultado sale
        success=False con ese AttributeError como mensaje de error. El worker
        no crashea, pero con un orchestrator real NUNCA devuelve exito.
        Si algun dia se corrige worker.py para leer los campos correctos
        (exito/respuesta/intencion/...), este test dejara de reflejar la
        realidad y habra que actualizarlo — eso es intencional.
        """
        from agents.orchestration_agent import OrchestrationResult

        resultado_real = OrchestrationResult(
            respuesta="Cuatro", intencion="general", confianza=0.95,
            agente_usado="GenerationAgent", exito=True,
        )
        mock_orchestrator.process = AsyncMock(return_value=resultado_real)

        from worker import _procesar_tarea
        result = await _procesar_tarea(mock_orchestrator, _make_task(), mock_redis)

        assert result["success"] is False
        assert "success" in result["error"]  # AttributeError: ...no attribute 'success'
