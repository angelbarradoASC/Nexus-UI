"""tests/unit/test_prospecting_llm_client.py

Tests unitarios para LocalLLMClient — en concreto, que provider="ollama"
desactiva el modo de razonamiento (think=False) y usa el endpoint NATIVO
de Ollama (/api/chat), no el compatible con OpenAI. Encontrado en vivo el
2026-08-29: via /v1/chat/completions, think=False NO elimina el
razonamiento del todo — se cuela dentro de "content" y agota max_tokens
antes de la respuesta real (una llamada real de reconstruccion devolvio
el razonamiento truncado en ingles en vez de la frase pedida). Via
/api/chat nativo, think=False lo elimina limpio — mismo modelo, mismo
prompt, cero fugas.
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
    captured_url: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url: str, *, headers: dict, json: dict) -> _FakeResponse:
        _FakeAsyncClient.captured_payload = json
        _FakeAsyncClient.captured_url = url
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
async def test_ollama_provider_uses_native_endpoint_not_openai_compatible(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalLLMClient(settings=_settings(provider="ollama"))

    await client.complete(system_prompt="sistema", user_prompt="responde ok")

    assert _FakeAsyncClient.captured_url == "http://192.168.68.150:11434/api/chat"


@pytest.mark.asyncio
async def test_ollama_provider_uses_native_payload_shape(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalLLMClient(settings=_settings(provider="ollama"))

    await client.complete(system_prompt="sistema", user_prompt="responde ok", temperature=0.3, max_tokens=42)

    payload = _FakeAsyncClient.captured_payload
    assert payload["model"] == "qwen3:8b"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.3, "num_predict": 42}
    # Nunca top-level temperature/max_tokens (esos son del shim OpenAI-compat, no del nativo)
    assert "temperature" not in payload
    assert "max_tokens" not in payload


@pytest.mark.asyncio
async def test_non_ollama_provider_uses_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalLLMClient(settings=_settings(provider="openai_compatible"))

    await client.complete(system_prompt="sistema", user_prompt="responde ok", temperature=0.3, max_tokens=42)

    assert _FakeAsyncClient.captured_url == "http://192.168.68.150:11434/v1/chat/completions"
    payload = _FakeAsyncClient.captured_payload
    assert payload["temperature"] == 0.3
    assert payload["max_tokens"] == 42
    assert "options" not in payload


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
