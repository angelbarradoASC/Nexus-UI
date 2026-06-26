"""
tests/unit/test_llm_router.py
------------------------------
Tests unitarios para app/agents/llm_router.py.
No requiere LLM real — mockea httpx.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio


def make_http_response(content: str, status_code: int = 200) -> MagicMock:
    """Crea una respuesta httpx mockeada."""
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json = MagicMock(return_value=body)
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock
        )
    return mock


def make_http_response_with_reasoning(reasoning: str) -> MagicMock:
    body = {
        "choices": [{"message": {"content": None, "reasoning": reasoning}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json = MagicMock(return_value=body)
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def router(test_config):
    """LLMRouter configurado con L0 local de test."""
    patched_cfg = test_config.model_copy(
        update={
            "llm_l0_url": "http://localhost:1234/v1",
            "llm_api_base_url": None,
            "llm_l1_url": None,
            "llm_l1_key": None,
            "nvidia_use_as_l1": False,
            "nvidia_api_key": None,
        }
    )
    with patch("agents.llm_router.cfg", patched_cfg):
        from agents.llm_router import LLMRouter
        r = LLMRouter()
    return r


class TestCallExitoso:
    @pytest.mark.asyncio
    async def test_call_ok_devuelve_contenido(self, router):
        mock_resp = make_http_response("Hola, soy el LLM")

        with patch.object(router, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            from agents.llm_router import LLMResponse
            result = await router.call(
                [{"role": "user", "content": "hola"}],
                min_level=0,
            )

        assert result.error is None
        assert result.content == "Hola, soy el LLM"
        assert result.level_used == 0
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_openrouter_usa_headers_recomendados(self, test_config):
        patched_cfg = test_config.model_copy(
            update={
                "llm_l0_url": None,
                "llm_api_base_url": None,
                "llm_l1_url": "https://openrouter.ai/api/v1",
                "llm_l1_key": "openrouter-key",
                "llm_l1_model": "openrouter/free",
                "nvidia_use_as_l1": False,
                "nvidia_api_key": None,
            }
        )
        with patch("agents.llm_router.cfg", patched_cfg):
            from agents.llm_router import LLMRouter
            openrouter_router = LLMRouter()

        mock_resp = make_http_response("Hola")

        with patch.object(openrouter_router, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            await openrouter_router.call(
                [{"role": "user", "content": "hola"}],
                min_level=1,
                preferred_level=1,
            )

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer openrouter-key"
        assert kwargs["headers"]["HTTP-Referer"] == "https://nexus.local"
        assert kwargs["headers"]["X-Title"] == "Nexus"

    @pytest.mark.asyncio
    async def test_call_sin_niveles_configurados(self):
        """Si no hay niveles, devuelve error sin lanzar excepción."""
        with patch("agents.llm_router.cfg") as mock_cfg:
            mock_cfg.l0_url = None
            mock_cfg.l1_url = None
            mock_cfg.l1_key = None
            mock_cfg.l1_model = "test-model"
            mock_cfg.llm_l2_url = None
            mock_cfg.llm_l3_url = None
            mock_cfg.llm_priority = "cost"
            from agents.llm_router import LLMRouter
            router_vacio = LLMRouter()

        result = await router_vacio.call([{"role": "user", "content": "test"}])
        assert result.error == "no_levels_configured"

    @pytest.mark.asyncio
    async def test_call_fallback_a_reasoning_si_content_viene_vacio(self, router):
        mock_resp = make_http_response_with_reasoning("OK desde reasoning")

        with patch.object(router, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            result = await router.call(
                [{"role": "user", "content": "hola"}],
                min_level=0,
            )

        assert result.error is None
        assert result.content == "OK desde reasoning"


class TestRetries:
    @pytest.mark.asyncio
    async def test_reintenta_en_timeout(self, router):
        """Debe reintentar hasta MAX_RETRIES veces en timeout."""
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        with patch.object(router, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_get_client.return_value = mock_client

            result = await router.call([{"role": "user", "content": "test"}])

        assert result.error is not None
        assert "timeout" in result.error
        assert call_count == 3  # 1 intento + 2 reintentos = 3

    @pytest.mark.asyncio
    async def test_no_reintenta_en_401(self, router):
        """No debe reintentar en errores 4xx (salvo 429)."""
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = make_http_response("", 401)
            raise httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)

        with patch.object(router, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_get_client.return_value = mock_client

            result = await router.call([{"role": "user", "content": "test"}])

        assert call_count == 1  # Sin reintentos


class TestMetrics:
    @pytest.mark.asyncio
    async def test_metricas_se_actualizan_en_exito(self, router):
        mock_resp = make_http_response("respuesta")

        with patch.object(router, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            await router.call([{"role": "user", "content": "test"}])

        snapshot = router.metrics_snapshot()
        # Al menos un nivel tuvo una llamada exitosa
        assert any(v > 0 for v in snapshot["calls"].values())


class TestPrioridad:
    def test_prioridad_por_defecto_es_cost(self, router):
        from agents.llm_router import Prioridad
        assert router.prioridad == Prioridad.COSTE

    def test_candidatos_desde_nivel_0(self, router):
        candidatos = router._candidatos(0)
        assert 0 in candidatos  # L0 debe estar disponible

    def test_candidatos_desde_nivel_superior_al_disponible(self, router):
        """Si pedimos desde L3 pero solo hay L0, debe devolver L0."""
        candidatos = router._candidatos(3)
        assert len(candidatos) > 0  # fallback a lo disponible
