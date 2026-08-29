"""tests/unit/test_prospecting_embeddings.py

Tests unitarios para LocalEmbeddingsClient y cosine_similarity — el
mecanismo de comparación semántica usado por el chequeo de ida y vuelta
de la Campaña.
"""

from __future__ import annotations

import httpx
import pytest

from nexus.prospecting.embeddings import (
    LocalEmbeddingsClient,
    LocalEmbeddingsSettings,
    cosine_similarity,
)


# ── cosine_similarity — puro, sin red ───────────────────────────────────────

def test_identical_vectors_have_similarity_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_have_similarity_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_opposite_vectors_have_similarity_minus_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_empty_vectors_return_zero_not_error():
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], []) == 0.0


def test_mismatched_length_returns_zero_not_error():
    assert cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_zero_norm_vector_returns_zero_not_division_error():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── LocalEmbeddingsClient ────────────────────────────────────────────────────

def _settings(**overrides) -> LocalEmbeddingsSettings:
    base = dict(base_url="http://192.168.68.150:11434", model="nomic-embed-text", enabled=True, timeout=30.0)
    base.update(overrides)
    return LocalEmbeddingsSettings(**base)


def test_disabled_client_returns_none_without_network(monkeypatch):
    called = False

    class _ShouldNotBeCalled:
        def __init__(self, *a, **k):
            nonlocal called
            called = True

    monkeypatch.setattr(httpx, "AsyncClient", _ShouldNotBeCalled)
    client = LocalEmbeddingsClient(settings=_settings(enabled=False))

    import asyncio
    result = asyncio.run(client.embed("peluquerías en Zaragoza"))

    assert result is None
    assert called is False


def test_empty_text_returns_none():
    client = LocalEmbeddingsClient(settings=_settings())

    import asyncio
    result = asyncio.run(client.embed("   "))

    assert result is None


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    last_url: str | None = None
    last_json: dict | None = None
    response_payload: dict = {"embedding": [0.1, 0.2, 0.3]}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url: str, *, json: dict):
        _FakeAsyncClient.last_url = url
        _FakeAsyncClient.last_json = json
        return _FakeResponse(_FakeAsyncClient.response_payload)


@pytest.mark.asyncio
async def test_embed_calls_native_ollama_endpoint_not_openai_compatible(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalEmbeddingsClient(settings=_settings())

    result = await client.embed("peluquerías en Zaragoza")

    assert result == [0.1, 0.2, 0.3]
    assert _FakeAsyncClient.last_url == "http://192.168.68.150:11434/api/embeddings"
    assert _FakeAsyncClient.last_json == {"model": "nomic-embed-text", "prompt": "peluquerías en Zaragoza"}


@pytest.mark.asyncio
async def test_embed_returns_none_on_network_failure(monkeypatch):
    class _FailingClient(_FakeAsyncClient):
        async def post(self, url, *, json):
            raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    client = LocalEmbeddingsClient(settings=_settings())

    result = await client.embed("algo")

    assert result is None


@pytest.mark.asyncio
async def test_embed_returns_none_when_response_has_no_embedding(monkeypatch):
    _FakeAsyncClient.response_payload = {}
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = LocalEmbeddingsClient(settings=_settings())

    result = await client.embed("algo")

    assert result is None
    _FakeAsyncClient.response_payload = {"embedding": [0.1, 0.2, 0.3]}  # reset para otros tests
