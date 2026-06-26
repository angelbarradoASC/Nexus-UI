"""
tests/conftest.py
------------------
Fixtures compartidas para toda la batería de tests de NEXUS-UI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# ── Path ──────────────────────────────────────────────────────────────────────
# Añade /app al path para que los tests puedan importar los módulos de la app
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

# ── Stub de duckduckgo_search ─────────────────────────────────────────────────
# WebAgent usa duckduckgo_search. Si la librería no está instalada (entorno CI
# sin dependencias completas), los tests que importan cualquier módulo de agents/
# fallan en la cadena agents/__init__.py → OrchestrationAgent → WebAgent → web_search.
# El stub previene ese error de colección/ejecución: ningún test real llama a
# DuckDuckGo (WebAgent siempre se mockea), así que el stub no afecta los resultados.
try:
    import duckduckgo_search  # noqa: F401 — ya instalado, nada que hacer
except ImportError:
    _ddgs_stub = MagicMock()
    _ddgs_stub.DDGS = MagicMock()
    sys.modules["duckduckgo_search"] = _ddgs_stub
    sys.modules["duckduckgo_search.DDGS"] = _ddgs_stub.DDGS


# ── Variables de entorno de test ──────────────────────────────────────────────
# Se establecen ANTES de importar config para evitar errores de validación

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("APP_USERS", "testuser:testpass")
os.environ.setdefault("CREDENTIAL_STORE_KEY", "test-encryption-key-32chars-min!!")
os.environ.setdefault("LLM_API_BASE_URL", "http://localhost:1234/v1")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("MONGO_URI", "")  # Sin MongoDB en tests unitarios


# ── Fixtures de config ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_config():
    """AppConfig con valores de test seguros."""
    from config import AppConfig
    return AppConfig(
        debug=True,
        secret_key="test-secret-key-32-chars-minimum!!",
        app_users="testuser:testpass,admin:adminpass",
        credential_store_key="test-encryption-key-32chars-min!!",
        llm_api_base_url="http://localhost:1234/v1",
        redis_host="localhost",
        mongo_uri=None,
    )


# ── Fixtures de auth ──────────────────────────────────────────────────────────

@pytest.fixture
def session_auth(test_config):
    """SessionAuth inicializado con usuarios de test."""
    from utils.session_auth import SessionAuth
    return SessionAuth(test_config)


# ── Fixtures de LLM ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm_router():
    """LLMRouter con call() mockeado para tests sin LLM real."""
    from agents.llm_router import LLMResponse, LLMRouter
    router = MagicMock(spec=LLMRouter)
    router.call = AsyncMock(return_value=LLMResponse(
        content="Respuesta de test del LLM.",
        level_used=0,
        model_used="test-model",
        nivel_name="L0-Test",
        latency_ms=50,
    ))
    router.available_levels = MagicMock(return_value=[0])
    router.metrics_snapshot = MagicMock(return_value={})
    return router


@pytest.fixture
def mock_llm_router_error():
    """LLMRouter que siempre devuelve error — para tests de resiliencia."""
    from agents.llm_router import LLMResponse, LLMRouter
    router = MagicMock(spec=LLMRouter)
    router.call = AsyncMock(return_value=LLMResponse(
        content="",
        level_used=-1,
        model_used="none",
        error="timeout | nivel=L0-Test | 5000ms",
    ))
    return router


@pytest.fixture
def mock_llm_router_stream():
    """
    LLMRouter con call_stream() mockeado como async generator.
    Emite 3 chunks fijos para tests de streaming.
    """
    from agents.llm_router import LLMResponse, LLMRouter

    async def _fake_stream(*args, **kwargs):
        for chunk in ["Hola", " mundo", " streaming"]:
            yield chunk

    router = MagicMock(spec=LLMRouter)
    router.call = AsyncMock(return_value=LLMResponse(
        content="Hola mundo streaming",
        level_used=0,
        model_used="test-model",
        nivel_name="L0-Test",
        latency_ms=50,
    ))
    router.call_stream = MagicMock(side_effect=_fake_stream)
    router.available_levels = MagicMock(return_value=[0])
    router.metrics_snapshot = MagicMock(return_value={})
    return router


# ── Fixtures de CredentialStore ───────────────────────────────────────────────

@pytest.fixture
def credential_store(tmp_path, test_config):
    """CredentialStore en directorio temporal — no toca el store real."""
    from unittest.mock import patch
    from agents.tools.credential_store import CredentialStore

    store_file = tmp_path / "test_creds.enc"
    with patch.object(test_config, "credential_store_path", str(store_file)):
        with patch("agents.tools.credential_store.cfg", test_config):
            store = CredentialStore()
            # Sobreescribir la ruta al tmp
            store._store_file = store_file
            yield store


# ── Fixtures FastAPI ──────────────────────────────────────────────────────────

@pytest.fixture
def app_client(test_config, mock_llm_router):
    """Cliente de test para la FastAPI app."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock

    # Mock Redis para no necesitar Redis real
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.rpop = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    with patch("main._redis", mock_redis), \
         patch("main.cfg", test_config), \
         patch("agents.llm_router._router", mock_llm_router):
        import main as app_module
        from utils.session_auth import SessionAuth
        app_module._session_auth = SessionAuth(test_config)
        app_module._redis = mock_redis

        with TestClient(app_module.app, raise_server_exceptions=True) as client:
            yield client
