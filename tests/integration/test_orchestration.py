"""
tests/integration/test_orchestration.py
-----------------------------------------
Tests de integración del flujo completo de orquestación.
Mockea el LLMRouter — no requiere LLM ni servicios externos.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


def make_router(intention_response: dict, generation_response: str = "Respuesta generada."):
    """
    Crea un router que:
      - En la primera llamada devuelve el JSON de clasificación (IntentionAgent)
      - En las siguientes devuelve la respuesta de texto (GenerationAgent, etc.)
    """
    from agents.llm_router import LLMResponse, LLMRouter

    call_count = 0

    async def mock_call(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Primera llamada = clasificación
            return LLMResponse(
                content=json.dumps(intention_response),
                level_used=0, model_used="test",
            )
        else:
            # Resto = generación de texto
            return LLMResponse(
                content=generation_response,
                level_used=0, model_used="test",
                latency_ms=100,
            )

    router = MagicMock(spec=LLMRouter)
    router.call = mock_call
    router.available_levels = MagicMock(return_value=[0])
    return router


@pytest.fixture
def orchestrator_general():
    """Orquestador que clasifica como 'general'."""
    router = make_router(
        intention_response={"intention": "general", "entities": {}, "confidence": 0.99},
        generation_response="Esta es mi respuesta para una consulta general.",
    )
    with patch("agents.orchestration_agent.get_router", return_value=router):
        from agents.orchestration_agent import OrchestrationAgent
        return OrchestrationAgent()


@pytest.fixture
def orchestrator_ssh():
    """Orquestador que clasifica como diagnóstico SSH."""
    router = make_router(
        intention_response={
            "intention": "diagnostico_servidor",
            "entities": {"servidor": "web-prod-01"},
            "confidence": 0.95,
        },
        generation_response="El servidor parece estar bien.",
    )
    with patch("agents.orchestration_agent.get_router", return_value=router):
        from agents.orchestration_agent import OrchestrationAgent
        orch = OrchestrationAgent()
    return orch


class TestFlujoGeneral:
    @pytest.mark.asyncio
    async def test_consulta_general_devuelve_respuesta(self, orchestrator_general):
        result = await orchestrator_general.process_query(
            user_query="¿Cuánto es 2+2?",
            username="testuser",
            history=[],
        )
        assert result.exito is True
        assert "general" in result.intencion
        assert len(result.respuesta) > 0

    @pytest.mark.asyncio
    async def test_resultado_contiene_audit_dict(self, orchestrator_general):
        result = await orchestrator_general.process_query(
            user_query="hola",
            username="testuser",
            history=[],
        )
        audit = result.audit_dict()
        assert "intention" in audit
        assert "confidence" in audit
        assert "agent" in audit
        assert "success" in audit

    @pytest.mark.asyncio
    async def test_historial_se_pasa_correctamente(self, orchestrator_general):
        """Verifica que el historial no rompe el flujo."""
        history = [
            {"role": "user", "content": "Mensaje anterior"},
            {"role": "assistant", "content": "Respuesta anterior"},
        ]
        result = await orchestrator_general.process_query(
            user_query="¿Y ahora?",
            username="testuser",
            history=history,
        )
        assert result.exito is True


class TestFlujoFollowUp:
    @pytest.mark.asyncio
    async def test_follow_up_si_falta_servidor(self):
        """Si el usuario pide diagnóstico sin especificar servidor, debe preguntar."""
        router = make_router(
            intention_response={
                "intention": "diagnostico_servidor",
                "entities": {"servidor": None},  # Sin servidor
                "confidence": 0.8,
            },
            generation_response="¿Qué servidor quieres diagnosticar?",
        )
        with patch("agents.orchestration_agent.get_router", return_value=router):
            from agents.orchestration_agent import OrchestrationAgent
            orch = OrchestrationAgent()

        result = await orch.process_query(
            user_query="revisa el servidor",
            username="testuser",
            history=[],
        )
        assert result.agente_usado == "intention_followup"
        assert "?" in result.respuesta or len(result.respuesta) > 0


class TestFlujoSSH:
    @pytest.mark.asyncio
    async def test_ssh_sin_credenciales_devuelve_error_amigable(self, orchestrator_ssh):
        """SSH agent debe manejar la falta de credenciales sin lanzar excepción."""
        with patch("agents.tools.credential_store.CredentialStore.get", return_value=None), \
             patch("agents.tools.host_resolver.HostResolver.resolver",
                   return_value={"ip": "192.168.1.1", "nombre": "web-prod-01"}):
            result = await orchestrator_ssh.process_query(
                user_query="revisa web-prod-01",
                username="testuser",
                history=[],
            )
        # Debe responder, no explotar
        assert result.respuesta
        assert result.exito is False  # Sin creds = fallo controlado


class TestResiliencia:
    @pytest.mark.asyncio
    async def test_error_inesperado_en_agente_devuelve_respuesta_generica(self):
        """Si un agente lanza una excepción inesperada, el orquestador debe absorberla."""
        router = make_router(
            intention_response={"intention": "general", "entities": {}, "confidence": 0.9},
        )
        with patch("agents.orchestration_agent.get_router", return_value=router):
            from agents.orchestration_agent import OrchestrationAgent
            orch = OrchestrationAgent()

        # Hacer que el agente general explote
        with patch.object(orch._agents["general"], "ejecutar",
                          side_effect=RuntimeError("error inesperado")):
            result = await orch.process_query("test", "user", [])

        assert result.exito is False
        assert result.respuesta  # Debe haber alguna respuesta amigable


class TestContratoResult:
    @pytest.mark.asyncio
    async def test_result_tiene_todos_los_campos(self, orchestrator_general):
        result = await orchestrator_general.process_query("test", "user", [])
        assert hasattr(result, "respuesta")
        assert hasattr(result, "thinking")
        assert hasattr(result, "intencion")
        assert hasattr(result, "confianza")
        assert hasattr(result, "agente_usado")
        assert hasattr(result, "datos")
        assert hasattr(result, "exito")

    @pytest.mark.asyncio
    async def test_audit_dict_serializable(self, orchestrator_general):
        """audit_dict() debe producir algo JSON-serializable."""
        result = await orchestrator_general.process_query("test", "user", [])
        audit = result.audit_dict()
        json.dumps(audit)  # No debe lanzar
