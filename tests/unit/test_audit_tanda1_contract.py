from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import AsyncMock, MagicMock, patch

from desktop.config import DesktopSettings
from desktop.storage.local_state import DesktopLocalState
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


def _load_desktop_backend(tmp_path: Path):
    env = {
        "DEBUG": "true",
        "NEXUS_CONTEXT": "desktop_app",
        "APP_USERS": "audit:audit-pass",
        "SECRET_KEY": "audit-secret-key-32-characters!!",
        "CREDENTIAL_STORE_KEY": "audit-store-key-32-characters!!",
        "OPEN_NEXUS_DATA_DIR": str(tmp_path),
        "LOCALAPPDATA": str(tmp_path),
    }
    secret_store = DesktopProviderSecretStore(_FakeSecretBackend())
    with patch.dict("os.environ", env, clear=False), patch(
        "desktop.storage.local_state.build_desktop_provider_secret_store",
        return_value=secret_store,
    ):
        import config as config_module
        import desktop.storage.local_state as local_state_module
        from products.desktop.backend import app as desktop_app_module

        importlib.reload(config_module)
        app_module = importlib.reload(desktop_app_module)
        local_state_module.build_desktop_provider_secret_store = lambda: secret_store
        app_module._get_desktop_local_state = lambda: DesktopLocalState(
            DesktopSettings.from_env(),
            provider_secret_store=secret_store,
        )

        @asynccontextmanager
        async def _noop_lifespan(_app):
            yield

        app_module.app.router.lifespan_context = _noop_lifespan
        app_module._session_auth = app_module.SessionAuth(app_module.cfg)
        app_module.app.state.session_auth = app_module._session_auth
        app_module.app.state.llm_router = MagicMock(close=AsyncMock())
        return app_module


def test_desktop_backend_arranca_y_health_sigue_estable(tmp_path):
    from fastapi.testclient import TestClient

    app_module = _load_desktop_backend(tmp_path)

    with TestClient(app_module.app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": app_module.cfg.app_version,
        "redis": False,
        "mongodb": False,
        "sessions": 0,
        "context": "desktop_app",
        "backend": "desktop",
    }


def test_login_valido_conserva_redireccion_esperada(tmp_path):
    from fastapi.testclient import TestClient

    app_module = _load_desktop_backend(tmp_path)

    with TestClient(app_module.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/login",
            data={"username": "audit", "password": "audit-pass"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/open-nexus"
    assert "session_token=" in response.headers.get("set-cookie", "")


def test_login_invalido_conserva_redireccion_esperada(tmp_path):
    from fastapi.testclient import TestClient

    app_module = _load_desktop_backend(tmp_path)

    with TestClient(app_module.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/login",
            data={"username": "audit", "password": "incorrecta"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert unquote(response.headers["location"]) == "/login?error=Credenciales incorrectas"


def test_provider_config_no_devuelve_secreto_completo_ni_rompe_claves_publicas(tmp_path):
    from fastapi.testclient import TestClient

    app_module = _load_desktop_backend(tmp_path)

    async def _fake_reload(_app):
        return app_module._load_desktop_provider_config()

    with patch.object(app_module, "_reload_desktop_provider_runtime", side_effect=_fake_reload):
        with TestClient(app_module.app, raise_server_exceptions=False) as client:
            save_response = client.put(
                "/api/desktop/providers",
                json={
                    "provider_type": "openai_compatible",
                    "provider_label": "Audit remoto",
                    "api_base_url": "https://llm.audit.example/v1",
                    "api_key": "sk-audit-secret-1234567890",
                    "model": "audit-model",
                    "enabled": True,
                },
            )
            get_response = client.get("/api/desktop/providers")

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["provider"]["provider_label"] == "Audit remoto"
    assert saved["provider"]["api_base_url"] == "https://llm.audit.example/v1"
    assert saved["provider"]["model"] == "audit-model"
    assert saved["provider"]["enabled"] is True
    assert saved["provider"]["api_key"] != "sk-audit-secret-1234567890"

    loaded = get_response.json()
    assert loaded["configured"] is True
    assert loaded["applied"] is True
    assert loaded["provider"]["provider_label"] == "Audit remoto"
    assert loaded["provider"]["api_base_url"] == "https://llm.audit.example/v1"
    assert loaded["provider"]["model"] == "audit-model"
    assert loaded["provider"]["enabled"] is True
    assert loaded["provider"]["api_key"] != "sk-audit-secret-1234567890"



