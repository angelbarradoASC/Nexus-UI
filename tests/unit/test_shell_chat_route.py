"""tests/unit/test_shell_chat_route.py

El chat del Shell (pagina Open-Nexus) tiene que hablar con el LLM local en
192.168.68.150 (mismo LOCAL_LLM_* que ya usan Campaña/Prospeccion) en vez
del router de Groq compartido que usa PEPO — pedido explicito del usuario.
Cubre el endpoint aislado (sin arrancar la app Desktop completa).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies.auth import get_prospecting_manager
from nexus.api.routes import shell as shell_route


class _FakeLocalLLM:
    def __init__(self, *, enabled: bool, model: str = "qwen3:8b", response: str = ""):
        self._enabled = enabled
        self._response = response
        self.calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def descriptor(self) -> dict:
        return {"enabled": self._enabled, "model": "qwen3:8b" if self._enabled else "", "base_url": "http://192.168.68.150:11434"}

    async def complete(self, *, system_prompt, user_prompt, temperature=None, max_tokens=None):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._response


class _FakeProspecting:
    def __init__(self, llm):
        self.local_llm = llm


def _client(llm) -> TestClient:
    app = FastAPI()
    app.include_router(shell_route.router, prefix="/api/nexus")
    app.dependency_overrides[get_prospecting_manager] = lambda: _FakeProspecting(llm)
    return TestClient(app)


def test_shell_chat_uses_local_llm_not_groq_router():
    llm = _FakeLocalLLM(enabled=True, response="Hola, soy el LLM local.")
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "Hola, soy el LLM local."
    assert body["available"] is True
    assert body["model"] == "qwen3:8b"
    assert llm.calls == [{"system_prompt": shell_route._SYSTEM_PROMPT, "user_prompt": "hola"}]


def test_shell_chat_reports_unavailable_when_local_llm_disabled():
    llm = _FakeLocalLLM(enabled=False)
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "192.168.68.150" in body["response"]
    assert llm.calls == []


def test_shell_chat_reports_unavailable_when_local_llm_returns_empty():
    llm = _FakeLocalLLM(enabled=True, response="")
    client = _client(llm)

    response = client.post("/api/nexus/shell/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "192.168.68.150" in body["response"]
