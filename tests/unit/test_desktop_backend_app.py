from __future__ import annotations

import importlib
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch


def test_desktop_backend_health_no_depende_de_redis_ni_mongo():
    import os

    temp_dir = tempfile.mkdtemp(prefix="open-nexus-desktop-backend-")

    with patch.dict(
        "os.environ",
        {
            "DEBUG": "true",
            "NEXUS_CONTEXT": "desktop_app",
            "OPEN_NEXUS_DATA_DIR": temp_dir,
        },
        clear=False,
    ):
        import config as config_module
        from fastapi.testclient import TestClient
        from products.desktop.backend import app as desktop_app_module
        importlib.reload(config_module)
        app_module = importlib.reload(desktop_app_module)

        fake_router = MagicMock()
        fake_router.close = AsyncMock()
        app_module.app.state.llm_router = fake_router

        with TestClient(app_module.app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["context"] == "desktop_app"
        assert body["backend"] == "desktop"
        assert body["redis"] is False
        assert body["mongodb"] is False
