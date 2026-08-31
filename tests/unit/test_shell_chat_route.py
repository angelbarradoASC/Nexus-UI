"""tests/unit/test_shell_chat_route.py

El chat del Shell (pagina Open-Nexus) tiene que hablar con el LLM local en
192.168.68.150 (mismo LOCAL_LLM_* que ya usan Campaña/Prospeccion) en vez
del router de Groq compartido que usa PEPO — pedido explicito del usuario.
Ademas debe poder USAR HERRAMIENTAS: qwen3:8b ya tiene tool-calling
activado en Ollama, y el toolbox inicial (estado de servicios, alarmas)
reutiliza lo que el propio panel de monitorizacion del Shell ya expone.
Cubre el endpoint aislado (sin arrancar la app Desktop completa).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies.auth import get_coordinator, get_prospecting_manager
from nexus.api.routes import shell as shell_route
from nexus.prospecting.llm import LocalToolCallResult


class _FakeLocalLLM:
    def __init__(self, *, enabled: bool, model: str = "qwen3:8b", responses: list[LocalToolCallResult] | None = None):
        self._enabled = enabled
        self._responses = list(responses or [])
        self.calls: list[list[dict]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def descriptor(self) -> dict:
        return {"enabled": self._enabled, "model": "qwen3:8b" if self._enabled else "", "base_url": "http://192.168.68.150:11434"}

    async def chat_with_tools(self, *, messages, tools):
        self.calls.append(messages)
        return self._responses.pop(0)


class _FakeProspecting:
    def __init__(self, llm):
        self.local_llm = llm


class _FakeCoordinator:
    def __init__(self, *, collector_status=None, incidents=None):
        self._collector_status = collector_status or {"status": "success", "overall": "up", "collectors": []}
        self._incidents = incidents or []
        self.tool_calls: list[str] = []

    async def get_collector_status(self):
        self.tool_calls.append("get_service_status")
        return self._collector_status

    async def list_incidents(self, limit=50):
        self.tool_calls.append("get_recent_alarms")
        from types import SimpleNamespace
        return SimpleNamespace(incidents=self._incidents[:limit])


def _client(llm, coordinator=None) -> TestClient:
    app = FastAPI()
    app.include_router(shell_route.router, prefix="/api/nexus")
    app.dependency_overrides[get_prospecting_manager] = lambda: _FakeProspecting(llm)
    app.dependency_overrides[get_coordinator] = lambda: coordinator or _FakeCoordinator()
    return TestClient(app)


def test_shell_chat_answers_directly_when_no_tool_needed():
    llm = _FakeLocalLLM(enabled=True, responses=[
        LocalToolCallResult(content="Hola, soy el LLM local.", tool_calls=[]),
    ])
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "Hola, soy el LLM local."
    assert body["available"] is True
    assert body["model"] == "qwen3:8b"


def test_shell_chat_uses_service_status_tool_and_returns_final_answer():
    llm = _FakeLocalLLM(enabled=True, responses=[
        LocalToolCallResult(content="", tool_calls=[{"function": {"name": "get_service_status", "arguments": {}}}]),
        LocalToolCallResult(content="Todo esta arriba.", tool_calls=[]),
    ])
    coordinator = _FakeCoordinator(collector_status={
        "status": "success", "overall": "up",
        "collectors": [{"name": "Prometheus", "status": "up"}],
    })
    client = _client(llm, coordinator)

    response = client.post("/api/nexus/shell/chat", json={"message": "como esta prometheus?"})

    assert response.status_code == 200
    assert response.json()["response"] == "Todo esta arriba."
    assert coordinator.tool_calls == ["get_service_status"]
    # el resultado de la herramienta se le devolvio al LLM antes de la respuesta final
    second_call_messages = llm.calls[1]
    assert second_call_messages[-1]["role"] == "tool"
    assert "Prometheus" in second_call_messages[-1]["content"]


def test_shell_chat_uses_alarms_tool_with_string_arguments():
    """Ollama normalmente entrega arguments como dict, pero el codigo debe
    tolerar que llegue como string JSON (mismo patron que otros clientes)."""
    llm = _FakeLocalLLM(enabled=True, responses=[
        LocalToolCallResult(content="", tool_calls=[{"function": {"name": "get_recent_alarms", "arguments": '{"limit": 2}'}}]),
        LocalToolCallResult(content="Hay 1 alarma activa.", tool_calls=[]),
    ])
    coordinator = _FakeCoordinator(incidents=[{"severity": "high", "title": "Disco lleno", "status": "open"}])
    client = _client(llm, coordinator)

    response = client.post("/api/nexus/shell/chat", json={"message": "hay alarmas?"})

    assert response.status_code == 200
    assert response.json()["response"] == "Hay 1 alarma activa."
    assert coordinator.tool_calls == ["get_recent_alarms"]


def test_shell_chat_reports_unavailable_when_local_llm_disabled():
    llm = _FakeLocalLLM(enabled=False)
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "192.168.68.150" in body["response"]
    assert llm.calls == []


def test_shell_chat_reports_unavailable_when_local_llm_errors():
    llm = _FakeLocalLLM(enabled=True, responses=[
        LocalToolCallResult(content="", tool_calls=[], error="ConnectTimeout"),
    ])
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "192.168.68.150" in body["response"]


def test_shell_chat_stops_after_max_tool_steps_to_avoid_infinite_loop():
    always_calls_tool = LocalToolCallResult(
        content="", tool_calls=[{"function": {"name": "get_service_status", "arguments": {}}}],
    )
    llm = _FakeLocalLLM(enabled=True, responses=[always_calls_tool] * shell_route._MAX_TOOL_STEPS)
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    assert llm.calls  # se llamo al menos una vez, pero no indefinidamente
    assert len(llm.calls) == shell_route._MAX_TOOL_STEPS
