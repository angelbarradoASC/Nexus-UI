from __future__ import annotations

import importlib
from contextlib import asynccontextmanager


EXPECTED_DESKTOP_ROUTES = [
    ("GET", "/"),
    ("GET", "/api/desktop/operator/integrations"),
    ("GET", "/api/desktop/runtime"),
    ("GET", "/api/desktop/settings/summary"),
    ("GET", "/api/desktop/providers"),
    ("GET", "/api/metrics"),
    ("GET", "/favicon.ico"),
    ("GET", "/health"),
    ("GET", "/login"),
    ("GET", "/logout"),
    ("GET", "/metrics"),
    ("GET", "/nexus/campaign"),
    ("GET", "/nexus/settings"),
    ("GET", "/nexus-sales"),
    ("GET", "/nexus-prompts"),
    ("GET", "/nexus-v1"),
    ("GET", "/nexus/vault"),
    ("GET", "/open-nexus"),
    ("GET", "/open-nexus/models"),
    ("POST", "/api/desktop/operator/integrations/test"),
    ("POST", "/api/desktop/operator/rdp"),
    ("POST", "/api/desktop/resolve"),
    ("POST", "/api/metrics/ingest"),
    ("POST", "/api/quick-action"),
    ("POST", "/login"),
    ("PUT", "/api/desktop/operator/integrations"),
    ("PUT", "/api/desktop/providers"),
    ("DELETE", "/api/desktop/operator/integrations/{integration_id}"),
]


def _load_apps():
    canonical_module = importlib.import_module("products.desktop.backend.app")
    legacy_module = importlib.import_module("desktop.backend.app")
    canonical_module = importlib.reload(canonical_module)
    legacy_module = importlib.reload(legacy_module)

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    canonical_module.app.router.lifespan_context = _noop_lifespan
    return canonical_module.app, legacy_module.app


def test_legacy_desktop_backend_app_is_canonical_app():
    canonical_app, legacy_app = _load_apps()

    assert legacy_app is canonical_app


def test_canonical_desktop_backend_preserves_expected_route_inventory():
    canonical_app, _ = _load_apps()
    routes = sorted(
        (method, route.path)
        for route in canonical_app.router.routes
        for method in sorted(getattr(route, "methods", []) or [])
        if route.path in {path for _, path in EXPECTED_DESKTOP_ROUTES}
    )

    assert routes == sorted(EXPECTED_DESKTOP_ROUTES)
