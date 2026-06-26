"""
tests/e2e/test_api.py
----------------------
Tests end-to-end de la API FastAPI.
Usa TestClient — no requiere servidor corriendo.
Mockea Redis y LLMRouter; MongoDB deshabilitado (MONGO_URI="").

NOTAS DE IMPLEMENTACIÓN:
- raise_server_exceptions=True: cualquier excepción no controlada en el servidor
  se propaga al test en lugar de convertirse en un 500 silencioso.
  HTTPException (401, 403, 503...) NO se ve afectada — FastAPI la maneja normalmente.
- Patch sobre "main.cfg" (no "config.cfg"): main.py importa cfg a nivel de módulo
  con `from config import cfg`; para que la referencia en main se parchee correctamente
  hay que usar "main.cfg".
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def client(test_config):
    """Cliente FastAPI de test con todas las dependencias mockeadas."""
    import os
    os.environ["DEBUG"] = "true"

    mock_redis = AsyncMock()
    mock_redis.ping   = AsyncMock(return_value=True)
    mock_redis.lpush  = AsyncMock(return_value=1)
    mock_redis.rpop   = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    from agents.llm_router import LLMResponse, LLMRouter
    mock_router = MagicMock(spec=LLMRouter)
    mock_router.call = AsyncMock(return_value=LLMResponse(
        content="Respuesta de test.", level_used=0, model_used="test",
    ))
    mock_router.close = AsyncMock()
    mock_router.available_levels = MagicMock(return_value=[0])

    # Patch "main.cfg" — no "config.cfg" — para que el código en main.py use test_config
    with patch("agents.llm_router._router", mock_router), \
         patch("main.cfg", test_config):

        from fastapi.testclient import TestClient
        import main as app_module

        from utils.session_auth import SessionAuth
        app_module._session_auth = SessionAuth(test_config)
        app_module._redis = mock_redis
        app_module.app.state.repo = MagicMock()
        app_module.app.state.repo.disponible = False

        with TestClient(app_module.app, raise_server_exceptions=True) as c:
            yield c


def login(client) -> str:
    """Helper: hace login y devuelve el token de sesión."""
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    return resp.cookies.get("session_token", "")


class TestAuth:
    def test_redirect_a_login_sin_sesion(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["location"]

    def test_login_correcto_redirige_a_root(self, client):
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "testpass"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_login_incorrecto_redirige_con_error(self, client):
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "wrongpass"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "error" in resp.headers["location"]

    def test_login_sets_cookie_httponly(self, client):
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "testpass"},
            follow_redirects=False,
        )
        cookie_header = resp.headers.get("set-cookie", "")
        assert "session_token" in cookie_header
        assert "httponly" in cookie_header.lower()

    def test_logout_redirige_a_login(self, client):
        login(client)
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["location"]

    def test_chat_sin_sesion_devuelve_401(self, client):
        resp = client.post("/chat", data={"user_message": "hola"})
        assert resp.status_code == 401


class TestChatEndpoint:
    def test_chat_con_sesion_encola_tarea(self, client):
        login(client)
        resp = client.post("/chat", data={"user_message": "hola"})
        assert resp.status_code == 200
        body = resp.json()
        assert "task_id" in body
        assert body["status"] == "processing"

    def test_task_id_es_string_no_vacio(self, client):
        login(client)
        resp = client.post("/chat", data={"user_message": "hola"})
        task_id = resp.json()["task_id"]
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    def test_check_response_sin_resultado_devuelve_processing(self, client):
        login(client)
        resp = client.get("/check_response/fake-task-id-123")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_check_response_con_resultado_devuelve_completed(self, client):
        result_data = {"response": "Hola!", "thinking": "", "audit": {}, "success": True}
        import main as app_module
        app_module._redis.rpop = AsyncMock(return_value=json.dumps(result_data))

        login(client)
        resp = client.get("/check_response/fake-task-id")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["data"]["response"] == "Hola!"

    def test_chat_selected_agent_acepta_analyst(self, client):
        login(client)
        resp = client.post("/chat", data={"user_message": "analiza", "selected_agent": "analyst"})
        assert resp.status_code == 200

    def test_chat_selected_agent_invalido_igual_procesa(self, client):
        """Overrides inválidos no rompen el endpoint — se normalizan a None."""
        login(client)
        resp = client.post("/chat", data={"user_message": "test", "selected_agent": "superagent"})
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health_devuelve_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "redis" in body

    def test_health_no_requiere_autenticacion(self, client):
        """El endpoint /health debe ser accesible sin sesión."""
        resp = client.get("/health")
        assert resp.status_code == 200


class TestDesktopEndpoints:
    def test_ingest_desde_localhost_acepta_metricas(self, client):
        resp = client.post(
            "/api/metrics/ingest",
            json={"metrics": {"cpu": 50}, "alerts": []},
        )
        assert resp.status_code == 200

    def test_quick_action_invalida_devuelve_400(self, client):
        resp = client.post(
            "/api/quick-action",
            json={"action": "accion_desconocida"},
        )
        assert resp.status_code == 400

    def test_quick_action_fichar_entrada_devuelve_ok(self, client):
        resp = client.post(
            "/api/quick-action",
            json={"action": "fichar_entrada"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestHistorialSinMongo:
    def test_history_sin_mongo_devuelve_503(self, client):
        login(client)
        resp = client.get("/api/history/testuser")
        assert resp.status_code == 503

    def test_history_sin_sesion_devuelve_401(self, client):
        resp = client.get("/api/history/testuser")
        assert resp.status_code == 401
