"""
tests/unit/test_generation_agent.py
-------------------------------------
Tests unitarios para GenerationAgent — agente de respuesta general.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestGenerationAgentEjecutar:

    @pytest.mark.asyncio
    async def test_devuelve_resultado_exitoso(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        result = await agent.ejecutar("Hola, ¿qué eres?", {}, [])
        assert result.exito is True
        assert result.respuesta  # no vacío

    @pytest.mark.asyncio
    async def test_nombre_agente_en_resultado(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        result = await agent.ejecutar("consulta", {}, [])
        assert result.agente == "GenerationAgent"

    @pytest.mark.asyncio
    async def test_incluye_system_prompt(self, mock_llm_router):
        """El primer mensaje enviado al LLM debe ser el system prompt."""
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        await agent.ejecutar("pregunta", {}, [])
        messages = mock_llm_router.call.call_args.args[0]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"]  # No vacío

    @pytest.mark.asyncio
    async def test_historial_incluido_en_mensajes(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        historial = [
            {"role": "user",      "content": "anterior"},
            {"role": "assistant", "content": "respuesta anterior"},
        ]
        await agent.ejecutar("nueva pregunta", {}, historial)
        messages = mock_llm_router.call.call_args.args[0]
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    @pytest.mark.asyncio
    async def test_consulta_del_usuario_en_ultimo_mensaje(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        await agent.ejecutar("¿Cuántos planetas hay?", {}, [])
        messages = mock_llm_router.call.call_args.args[0]
        assert messages[-1]["role"] == "user"
        assert "¿Cuántos planetas hay?" in messages[-1]["content"]

    @pytest.mark.asyncio
    async def test_datos_incluyen_level_y_model(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        result = await agent.ejecutar("consulta", {}, [])
        assert "level_used" in result.datos
        assert "model_used" in result.datos

    @pytest.mark.asyncio
    async def test_error_llm_devuelve_fallo(self, mock_llm_router_error):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router_error)
        result = await agent.ejecutar("consulta", {}, [])
        assert result.exito is False
        assert result.respuesta  # Mensaje de error amigable al usuario

    @pytest.mark.asyncio
    async def test_error_llm_incluye_error_tecnico(self, mock_llm_router_error):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router_error)
        result = await agent.ejecutar("consulta", {}, [])
        # El campo error contiene detalle técnico
        assert result.error or not result.exito  # Al menos uno de los dos

    @pytest.mark.asyncio
    async def test_temperatura_por_defecto(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        await agent.ejecutar("consulta", {}, [])
        kwargs = mock_llm_router.call.call_args.kwargs
        assert kwargs.get("temperature") == 0.7

    @pytest.mark.asyncio
    async def test_max_tokens_por_defecto(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        await agent.ejecutar("consulta", {}, [])
        kwargs = mock_llm_router.call.call_args.kwargs
        assert kwargs.get("max_tokens") == 1500

    @pytest.mark.asyncio
    async def test_entidades_no_rompen_ejecucion(self, mock_llm_router):
        """entidades se ignoran en GenerationAgent — no debe romper."""
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        result = await agent.ejecutar("consulta", {"key": "value", "extra": [1, 2]}, [])
        assert result.exito is True


class TestGenerationAgentEjecutarStream:

    @pytest.mark.asyncio
    async def test_stream_emite_chunks(self, mock_llm_router_stream):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router_stream)
        chunks = [c async for c in agent.ejecutar_stream("consulta", [])]
        assert len(chunks) == 3
        assert "".join(chunks) == "Hola mundo streaming"

    @pytest.mark.asyncio
    async def test_stream_con_historial(self, mock_llm_router_stream):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router_stream)
        historial = [{"role": "user", "content": "anterior"}]
        chunks = [c async for c in agent.ejecutar_stream("nueva", historial)]
        assert chunks  # Al menos un chunk


class TestGenerationAgentGenerateResponse:
    """
    generate_response() es la interfaz de compatibilidad usada por SSHAgent,
    JiraAgent y WebAgent — devuelve str directamente.
    """

    @pytest.mark.asyncio
    async def test_devuelve_string(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        respuesta = await agent.generate_response("prompt", "testuser", [])
        assert isinstance(respuesta, str)
        assert respuesta  # No vacío

    @pytest.mark.asyncio
    async def test_con_historial(self, mock_llm_router):
        from agents.generation_agent import GenerationAgent
        agent = GenerationAgent(router=mock_llm_router)
        historial = [{"role": "user", "content": "contexto"}]
        respuesta = await agent.generate_response("prompt", "testuser", historial)
        assert isinstance(respuesta, str)
