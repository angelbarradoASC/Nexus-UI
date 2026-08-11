"""FastAPI backend for the Open-Nexus desktop client.

This app is intentionally isolated from the legacy web/server stack:
- no Redis bootstrap
- no Mongo bootstrap
- no import from app/main.py

It still reuses domain services and Nexus API routes where that makes sense.

Los distintos grupos de endpoints viven en ficheros hermanos (`auth_routes`,
`rdp`, `metrics_routes`, `settings_routes`) montados aquí con
`include_router()` — este fichero solo monta la app, el lifespan, y las
rutas triviales que no encajan en ningún grupo.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel

from config import cfg
from desktop.branding import resolve_branding_icon
from desktop.config import DesktopSettings
from desktop.runtime.bootstrap import get_current_runtime
from desktop.storage.local_state import DesktopLocalState
from exceptions import register_exception_handlers
from nexus.api.dependencies.auth import build_runtime, upgrade_runtime_with_app_state
from products.desktop.backend import auth_routes, metrics_routes, rdp, settings_routes
from products.desktop.backend.auth_routes import get_session_auth
from products.desktop.backend.dependencies import get_desktop_local_state, get_desktop_settings
from products.desktop.backend.settings_routes import _get_monitoring_store, bootstrap_desktop_config
from products.desktop.bootstrap import register_desktop_product
from utils.logger import setup_logging
from utils.session_auth import SessionAuth

setup_logging(
    nivel=cfg.log_level,
    # Ruta absoluta fija (antes "logs/nexus.log" relativo — resolvia distinto
    # segun desde donde se lanzara el proceso; con el .exe compilado podia
    # acabar en cualquier sitio).
    archivo=(DesktopSettings.from_env().logs_dir / "nexus.log") if not cfg.debug else None,
)

APP_ROOT = Path(__file__).resolve().parents[3] / "products" / "desktop" / "ui"


if cfg.is_desktop:
    # Bootstrap de arranque: una sola construccion de DesktopSettings/
    # DesktopLocalState (no hay app.state todavia a nivel de modulo) y un
    # unico punto de entrada que aplica proveedor LLM + ventas + campaña +
    # ITSM sobre cfg — antes eran 4 llamadas sueltas a nivel de modulo.
    _bootstrap_local_state = DesktopLocalState(DesktopSettings.from_env())
    bootstrap_desktop_config(cfg, _bootstrap_local_state)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Open-Nexus Desktop backend arrancando | version={} | contexto={}",
        cfg.app_version,
        cfg.nexus_context,
    )

    # DesktopSettings/DesktopLocalState se construyen una vez aqui y se
    # reutilizan durante todo el ciclo de vida via Depends(get_desktop_*) —
    # antes cada handler de ruta las reconstruia desde cero en cada peticion.
    app.state.desktop_settings = DesktopSettings.from_env()
    app.state.desktop_local_state = DesktopLocalState(app.state.desktop_settings)

    app.state.session_auth = SessionAuth(cfg)
    logger.info("Desktop lifespan | SessionAuth listo")
    app.state.conversations = None
    if getattr(app.state, "nexus_runtime", None) is None:
        logger.info("Desktop lifespan | construyendo runtime")
        app.state.nexus_runtime = build_runtime(cfg)
        logger.info("Desktop lifespan | runtime construido")

    from agents.llm_router import get_router

    logger.info("Desktop lifespan | importes auxiliares listos")
    app.state.llm_router = get_router()
    logger.info("Desktop lifespan | router listo")
    upgrade_runtime_with_app_state(app, cfg)
    logger.info("Desktop lifespan | runtime actualizado")

    await app.state.llm_router.start_watchdog()
    logger.info("Desktop lifespan | watchdog LLM arrancado")

    from nexus.workers.scheduler import NexusScheduler

    scheduler = NexusScheduler()
    scheduler.attach_campaign_agent(app.state.nexus_runtime.campaign)
    scheduler.start()
    app.state.nexus_scheduler = scheduler
    logger.info("Desktop lifespan | scheduler de campaña arrancado")

    yield

    logger.info("Open-Nexus Desktop backend apagandose...")
    nexus_scheduler = getattr(app.state, "nexus_scheduler", None)
    if nexus_scheduler is not None:
        nexus_scheduler.stop()
    llm_router = getattr(app.state, "llm_router", None)
    if llm_router is not None:
        await llm_router.close()
    logger.info("Open-Nexus Desktop backend detenido limpiamente")


app = FastAPI(
    title="Open-Nexus Desktop",
    version=cfg.app_version,
    lifespan=lifespan,
    docs_url="/docs" if cfg.debug else None,
    redoc_url=None,
)

register_exception_handlers(app)
register_desktop_product(app)

os.makedirs(APP_ROOT / "static", exist_ok=True)
os.makedirs(APP_ROOT / "templates", exist_ok=True)
existing_route_names = {route.name for route in app.router.routes}
if "static" not in existing_route_names:
    app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))

app.include_router(auth_routes.router)
app.include_router(rdp.router)
app.include_router(metrics_routes.router)
app.include_router(settings_routes.router)


class _DesktopResolveBody(BaseModel):
    user_input: str


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/open-nexus", status_code=status.HTTP_302_FOUND)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.get("/health")
async def health(request: Request):
    auth = get_session_auth(request)
    llm_router = getattr(app.state, "llm_router", None)
    return {
        "status": "ok",
        "version": cfg.app_version,
        "redis": False,
        "mongodb": False,
        "sessions": auth.sesiones_activas() if auth else 0,
        "context": cfg.nexus_context,
        "backend": "desktop",
        "llm": llm_router.watchdog_snapshot() if llm_router else {"enabled": False},
    }


@app.get("/favicon.ico")
async def favicon():
    icon_path = resolve_branding_icon()
    if icon_path is not None:
        return FileResponse(icon_path, media_type="image/x-icon")
    return Response(content=b"", media_type="image/x-icon")


@app.get("/api/desktop/runtime")
async def get_desktop_runtime():
    runtime = get_current_runtime()
    if runtime is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Desktop runtime no disponible")
    return {"available": True, "runtime": runtime.describe()}


@app.get("/api/desktop/settings/summary")
async def get_desktop_settings_summary(
    settings: DesktopSettings = Depends(get_desktop_settings),
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    store = _get_monitoring_store(settings)
    integrations = store.list_integrations()
    by_kind: dict[str, int] = {}
    for item in integrations:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1

    return {
        "available": True,
        "context": cfg.nexus_context,
        "startup_url": settings.startup_url,
        "paths": {
            "root": str(settings.resolved_local_data_root),
            "config_dir": str(local_state.config_dir),
            "logs_dir": str(local_state.logs_dir),
            "history_dir": str(local_state.history_dir),
            "provider_file": str(local_state.llm_provider_config_path),
            "monitoring_db": str(settings.monitoring_config_db_path),
        },
        "monitoring": {
            "total_integrations": len(integrations),
            "by_kind": by_kind,
        },
    }


@app.post("/api/desktop/resolve")
async def resolve_desktop_skill(body: _DesktopResolveBody):
    runtime = get_current_runtime()
    if runtime is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Desktop runtime no disponible")
    return {"available": True, "resolution": runtime.resolve_user_input(body.user_input)}
