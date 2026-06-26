"""
tests/unit/test_base_agent.py
-------------------------------
Tests para AgentResult y BaseAgent (contrato de todos los agentes).
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ── AgentResult ───────────────────────────────────────────────────────────────

class TestAgentResult:

    def test_resultado_exitoso_defaults(self):
        from agents.base_agent import AgentResult
        r = AgentResult(respuesta="ok")
        assert r.exito is True
        assert r.agente == ""
        assert r.datos == {}
        assert r.error is None
        assert r.thinking == ""

    def test_factory_fallo(self):
        from agents.base_agent import AgentResult
        r = AgentResult.fallo("TestAgent", "Algo falló", "err_code")
        assert r.exito is False
        assert r.agente == "TestAgent"
        assert r.respuesta == "Algo falló"
        assert r.error == "err_code"

    def test_factory_fallo_sin_error_usa_mensaje(self):
        from agents.base_agent import AgentResult
        r = AgentResult.fallo("Agente", "Fallo")
        assert r.error == "Fallo"

    def test_resultado_serializable_a_dict(self):
        from agents.base_agent import AgentResult
        r = AgentResult(respuesta="texto", agente="Gen", datos={"k": "v"})
        d = r.model_dump()
        assert d["respuesta"] == "texto"
        assert d["datos"] == {"k": "v"}

    def test_datos_es_dict_vacio_por_defecto(self):
        from agents.base_agent import AgentResult
        r1 = AgentResult(respuesta="a")
        r2 = AgentResult(respuesta="b")
        # Cada instancia tiene su propio dict (no comparten referencia)
        r1.datos["x"] = 1
        assert "x" not in r2.datos

    def test_thinking_puede_ser_cadena_larga(self):
        from agents.base_agent import AgentResult
        thinking_largo = "razonamiento " * 200
        r = AgentResult(respuesta="ok", thinking=thinking_largo)
        assert r.thinking == thinking_largo


# ── BaseAgent (via subclase concreta) ─────────────────────────────────────────

class TestBaseAgent:
    """
    BaseAgent es abstracta — testeamos via una subclase mínima concreta.
    """

    @pytest.fixture
    def ConcreteAgent(self, mock_llm_router):
        """Devuelve una clase y una instancia de agente concreto."""
        from agents.base_agent import AgentResult, BaseAgent

        class _Concrete(BaseAgent):
            async def ejecutar(self, consulta, entidades, historial):
                return AgentResult(respuesta="concreto", agente=self._nombre())

        return _Concrete, _Concrete(router=mock_llm_router)

    def test_nombre_devuelve_nombre_clase(self, ConcreteAgent):
        _, agent = ConcreteAgent
        assert agent._nombre() == "_Concrete"

    def test_resultado_fallo_shortcut(self, ConcreteAgent):
        from agents.base_agent import AgentResult
        _, agent = ConcreteAgent
        r = agent._resultado_fallo("mensaje de error", "err")
        assert isinstance(r, AgentResult)
        assert r.exito is False
        assert r.respuesta == "mensaje de error"
        assert r.agente == "_Concrete"

    def test_resultado_fallo_sin_error_code(self, ConcreteAgent):
        _, agent = ConcreteAgent
        r = agent._resultado_fallo("error sin código")
        assert r.exito is False

    def test_construir_historial_ventana_vacio(self, ConcreteAgent):
        _, agent = ConcreteAgent
        assert agent._construir_historial_ventana([]) == []

    def test_construir_historial_ventana_trunca_a_6(self, ConcreteAgent):
        _, agent = ConcreteAgent
        historial = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        ventana = agent._construir_historial_ventana(historial)
        assert len(ventana) == 6
        # Los últimos 6
        assert ventana[-1]["content"] == "msg19"

    def test_construir_historial_ventana_max_turnos_custom(self, ConcreteAgent):
        _, agent = ConcreteAgent
        historial = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        ventana = agent._construir_historial_ventana(historial, max_turnos=3)
        assert len(ventana) == 3

    def test_construir_historial_ventana_menor_al_limite(self, ConcreteAgent):
        _, agent = ConcreteAgent
        historial = [{"role": "user", "content": "solo uno"}]
        ventana = agent._construir_historial_ventana(historial)
        assert len(ventana) == 1

    def test_router_inyectado(self, ConcreteAgent, mock_llm_router):
        _, agent = ConcreteAgent
        assert agent.router is mock_llm_router

    @pytest.mark.asyncio
    async def test_ejecutar_devuelve_agent_result(self, ConcreteAgent):
        from agents.base_agent import AgentResult
        _, agent = ConcreteAgent
        result = await agent.ejecutar("consulta", {}, [])
        assert isinstance(result, AgentResult)

    def test_no_se_puede_instanciar_directamente(self):
        from agents.base_agent import BaseAgent
        with pytest.raises(TypeError):
            BaseAgent(router=None)  # type: ignore
