"""tests/unit/test_prospecting_llm_client.py

Tests unitarios para LocalLLMClient — en concreto, que provider="ollama"
desactiva el modo de razonamiento (think=False) para no pagar el coste de
tokens de "pensar" en tareas de extraccion/verificacion JSON donde no hace
falta. Verificado en vivo contra el servidor real: 21.9s/206 tokens con
razonamiento activo frente a 9.8s sin el, para un prompt trivial.
"""

from __future__ import annotations

import json

import httpx
import pytest

from nexus.prospecting.llm import LocalLLMClient, LocalLLMSettings


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    captured_payload: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url: str, *, headers: dict, json: dict) -> _FakeResponse:
        _FakeAsyncClient.captured_payload = json
        return _FakeResponse({"message": {"content": "ok"}})


def _settings(**overrides) -> LocalLLMSettings:
    base = dict(
        base_url="http://192.168.68.150:11434",
        model="qwen3:8b",
        provider="ollama",
        enabled=True,
        timeout=20.0,
        retries=1,
    )
    base.update(overrides)
    return LocalLLMSettings(**base)


@pytest.mark.asyncio
async def test_ollama_provider_sends_think_false(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalLLMClient(settings=_settings(provider="ollama"))

    result = await client.complete(system_prompt="sistema", user_prompt="responde ok")

    assert result == "ok"
    assert _FakeAsyncClient.captured_payload["think"] is False


@pytest.mark.asyncio
async def test_non_ollama_provider_does_not_send_think(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalLLMClient(settings=_settings(provider="openai_compatible"))

    await client.complete(system_prompt="sistema", user_prompt="responde ok")

    assert "think" not in _FakeAsyncClient.captured_payload


@pytest.mark.asyncio
async def test_disabled_client_never_calls_http(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured_payload = None
    client = LocalLLMClient(settings=_settings(enabled=False))

    result = await client.complete(system_prompt="sistema", user_prompt="responde ok")

    assert result == ""
    assert _FakeAsyncClient.captured_payload is None
