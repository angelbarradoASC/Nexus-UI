"""
tests/smoke/test_smoke_desktop.py
-----------------------------------
Smoke tests del modo desktop.
Verifican que los endpoints de tray arrancan y responden correctamente
con y sin DESKTOP_INTERNAL_TOKEN configurado.

Estos tests son smoke — solo verifican que las rutas críticas
no están rotas, no la lógica de negocio completa.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nexus.security.desktop_secret_store import DesktopProviderSecretStore


class _FakeSecretBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


@pytest.fixture
def desktop_client(test_config):
    """Cliente con NEXUS_CONTEXT=desktop_app y token interno configurado."""
    import os
    os.environ["DEBUG"] = "true"

    temp_dir = tempfile.mkdtemp(prefix="open-nexus-desktop-")
    desktop_cfg = test_config.model_copy(update={
        "nexus_context": "desktop_app",
        "desktop_internal_token": "test-internal-token-123",
    })

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.rpop = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    from agents.llm_router import LLMResponse, LLMRouter
    mock_router = MagicMock(spec=LLMRouter)
    mock_router.close = AsyncMock()
    mock_router.available_levels = MagicMock(return_value=[0])
    secret_store = DesktopProviderSecretStore(_FakeSecretBackend())

    with patch.dict(
        "os.environ",
        {
            "DEBUG": "true",
            "NEXUS_CONTEXT": "desktop_app",
            "OPEN_NEXUS_DATA_DIR": temp_dir,
        },
        clear=False,
    ), patch("config.cfg", desktop_cfg), patch("agents.llm_router._router", mock_router), patch(
        "desktop.storage.local_state.build_desktop_provider_secret_store",
        return_value=secret_store,
    ):
        from fastapi.testclient import TestClient
        from products.desktop.backend import app as desktop_app_module
        app_module = importlib.reload(desktop_app_module)

        from desktop.config import DesktopSettings
        from desktop.runtime.assistant_runtime import DesktopAssistantRuntime
        from desktop.runtime.bootstrap import set_current_runtime
        from utils.session_auth import SessionAuth
        app_module._session_auth = SessionAuth(desktop_cfg)
        app_module._redis = mock_redis
        app_module.app.state.repo = MagicMock()
        app_module.app.state.repo.disponible = False
        set_current_runtime(
            DesktopAssistantRuntime(
                DesktopSettings(
                    app_port=desktop_cfg.app_port,
                    nexus_context=desktop_cfg.nexus_context,
                    host="127.0.0.1",
                    startup_timeout_seconds=15,
                    monitoring_interval_seconds=30,
                    desktop_internal_token=desktop_cfg.desktop_internal_token,
                    debug=True,
                    local_data_root=temp_dir,
                )
            )
        )

        with TestClient(app_module.app, raise_server_exceptions=False) as c:
            yield c, desktop_cfg.desktop_internal_token


class TestDesktopToken:
    def test_ingest_con_token_correcto_ok(self, desktop_client):
        client, token = desktop_client
        resp = client.post(
            "/api/metrics/ingest",
            json={"metrics": {"cpu": 42}, "alerts": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_ingest_sin_token_devuelve_401(self, desktop_client):
        client, _ = desktop_client
        resp = client.post(
            "/api/metrics/ingest",
            json={"metrics": {}, "alerts": []},
            # Sin header Authorization
        )
        assert resp.status_code == 401

    def test_ingest_con_token_incorrecto_devuelve_403(self, desktop_client):
        client, _ = desktop_client
        resp = client.post(
            "/api/metrics/ingest",
            json={"metrics": {}, "alerts": []},
            headers={"Authorization": "Bearer token-equivocado"},
        )
        assert resp.status_code == 403

    def test_quick_action_con_token_ok(self, desktop_client):
        client, token = desktop_client
        resp = client.post(
            "/api/quick-action",
            json={"action": "fichar_entrada"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_metrics_endpoint_disponible_en_desktop(self, desktop_client):
        client, _ = desktop_client

        # Login para poder acceder a /api/metrics
        client.post("/login", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True

    def test_prometheus_metrics_endpoint_expone_series(self, desktop_client):
        client, _ = desktop_client
        from products.desktop.backend import app as app_module

        app_module.app.state.nexus_runtime.coordinator.get_collector_status = AsyncMock(
            return_value={
                "status": "success",
                "overall": "degraded",
                "collectors": [
                    {"name": "Prometheus", "kind": "collector", "status": "up", "endpoint": "http://prometheus:9090"},
                    {"name": "Grafana", "kind": "visualization", "status": "up", "endpoint": "http://grafana:3000"},
                    {"name": "Alertmanager", "kind": "alarm-routing", "status": "down", "endpoint": "http://alertmanager:9093"},
                ],
            }
        )
        app_module.app.state.llm_router.metrics_snapshot = MagicMock(
            return_value={
                "calls": {"L1-Groq": 4},
                "failures": {"L1-Groq": 1},
                "avg_latency_ms": {"L1-Groq": 123.4},
            }
        )

        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "nexus_chat_requests_total" in resp.text
        assert "nexus_collector_status" in resp.text
        assert "nexus_llm_router_calls_total" in resp.text

    def test_runtime_endpoint_expone_capacidades_desktop(self, desktop_client):
        client, _ = desktop_client
        client.post("/login", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)
        resp = client.get("/api/desktop/runtime")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["runtime"]["surface"] == "desktop"
        assert len(body["runtime"]["capabilities"]) >= 5

    def test_resolve_endpoint_clasifica_skill_desktop(self, desktop_client):
        client, _ = desktop_client
        client.post("/login", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)
        resp = client.post(
            "/api/desktop/resolve",
            json={"user_input": "diagnostica el servidor web-prod-01"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["resolution"]["skill_id"] == "ssh.diagnostico"

    def test_provider_config_endpoints_desktop(self, desktop_client):
        client, _ = desktop_client
        client.post("/login", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)

        get_resp = client.get("/api/desktop/providers")
        assert get_resp.status_code == 200
        assert get_resp.json()["available"] is True

        from desktop.storage.provider_config import DesktopLLMProviderConfig
        with patch(
            "products.desktop.backend.app._reload_desktop_provider_runtime",
            AsyncMock(
                return_value=DesktopLLMProviderConfig(
                    provider_label="Servidor Claude",
                    api_base_url="https://llm.example.com/v1",
                    api_key="secret-1234",
                    model="claude-sonnet-4",
                    enabled=True,
                )
            ),
        ):
            put_resp = client.put(
                "/api/desktop/providers",
                json={
                    "provider_label": "Servidor Claude",
                    "provider_type": "openai_compatible",
                    "api_base_url": "https://llm.example.com/v1",
                    "api_key": "secret-1234",
                    "model": "claude-sonnet-4",
                    "enabled": True,
                },
            )

        assert put_resp.status_code == 200
        assert put_resp.json()["status"] == "saved"
        assert put_resp.json()["provider"]["model"] == "claude-sonnet-4"

    def test_monitoring_integration_endpoints_desktop(self, desktop_client):
        client, _ = desktop_client
        client.post("/login", data={"username": "testuser", "password": "testpass"}, follow_redirects=False)

        list_resp = client.get("/api/desktop/operator/integrations")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body["available"] is True
        assert any(item["kind"] == "prometheus" for item in body["integrations"])

        put_resp = client.put(
            "/api/desktop/operator/integrations",
            json={
                "kind": "prometheus",
                "name": "Prometheus laboratorio",
                "base_url": "http://192.168.1.151:9090",
                "enabled": True,
                "is_default": True,
            },
        )
        assert put_resp.status_code == 200
        saved_id = put_resp.json()["integration"]["integration_id"]

        list_after = client.get("/api/desktop/operator/integrations")
        assert list_after.status_code == 200
        entries = list_after.json()["integrations"]
        assert any(
            item["integration_id"] == saved_id and item["base_url"] == "http://192.168.1.151:9090"
            for item in entries
        )

        delete_resp = client.delete(f"/api/desktop/operator/integrations/{saved_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "deleted"


class TestSmoke:
    def test_health_ok(self, desktop_client):
        client, _ = desktop_client
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["context"] == "desktop_app"

    def test_login_page_carga(self, desktop_client):
        client, _ = desktop_client
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_favicon_no_rompe(self, desktop_client):
        client, _ = desktop_client
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")
        if Path("products/desktop/ui/static/favicon.ico").exists():
            assert len(resp.content) > 0

    def test_settings_page_carga(self, desktop_client):
        client, _ = desktop_client
        resp = client.get("/nexus/settings")
        assert resp.status_code == 200
        assert "Configuracion" in resp.text
