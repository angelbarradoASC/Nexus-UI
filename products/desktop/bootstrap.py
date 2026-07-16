"""Bootstrap entrypoints for the desktop product surface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import cfg
from nexus.api.dependencies.auth import build_runtime
from nexus.api.routes.audit import router as audit_router
from nexus.api.routes.agents import router as agents_router
from nexus.api.routes.chat import router as chat_router
from nexus.api.routes.crm import router as crm_router
from nexus.api.routes.assets_ops import router as assets_ops_router
from nexus.api.routes.health import router as health_router
from nexus.api.routes.incidents import router as incidents_router
from nexus.api.routes.monitoring import router as monitoring_router
from nexus.api.routes.outreach import router as outreach_router
from nexus.api.routes.prospecting import router as prospecting_router
from nexus.api.routes.prompts import router as prompts_router
from nexus.api.routes.approvals import router as approvals_router
from nexus.api.routes.cmdb import router as cmdb_router
from nexus.api.routes.vault import router as vault_router
from products.desktop.routes.ui import router as ui_router

_DESKTOP_ROOT = Path(__file__).resolve().parent


def register_desktop_product(app: FastAPI) -> None:
    if getattr(app.state, "nexus_runtime", None) is None:
        app.state.nexus_runtime = build_runtime(cfg)

    static_dir = _DESKTOP_ROOT / "ui" / "static"
    existing_route_names = {route.name for route in app.router.routes}
    if static_dir.exists() and "static" not in existing_route_names:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(health_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(agents_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(chat_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(incidents_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(monitoring_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(audit_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(assets_ops_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(crm_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(outreach_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(prospecting_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(prompts_router,  prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(approvals_router, prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(cmdb_router,      prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(vault_router,     prefix="/api/nexus", tags=["desktop-nexus"])
    app.include_router(ui_router, tags=["desktop-product-ui"])
