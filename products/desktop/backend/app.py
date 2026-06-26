"""FastAPI backend for the Open-Nexus desktop client.

This app is intentionally isolated from the legacy web/server stack:
- no Redis bootstrap
- no Mongo bootstrap
- no import from app/main.py

It still reuses domain services and Nexus API routes where that makes sense.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel

from config import cfg
from desktop.config import DesktopSettings
from desktop.runtime.bootstrap import get_current_runtime
from desktop.runtime.llm_provider_runtime import apply_desktop_provider_to_cfg
from desktop.storage.local_state import DesktopLocalState
from desktop.branding import resolve_branding_icon
from desktop.storage.monitoring_integrations import (
    DesktopMonitoringIntegration,
    DesktopMonitoringIntegrationStore,
)
from desktop.storage.provider_config import DesktopLLMProviderConfig
from exceptions import register_exception_handlers
from metrics import (
    metrics_response_body,
    metrics_response_content_type,
    update_collector_metrics,
    update_desktop_bridge_metrics,
    update_llm_router_metrics,
)
from nexus.api.dependencies.auth import build_runtime, upgrade_runtime_with_app_state
from nexus.connectors.observability.alertmanager import AlertmanagerConnector
from nexus.connectors.observability.grafana import GrafanaConnector
from nexus.connectors.observability.prometheus import PrometheusConnector
from products.desktop.bootstrap import register_desktop_product
from utils.logger import setup_logging
from utils.session_auth import SessionAuth

setup_logging(
    nivel=cfg.log_level,
    archivo=Path("logs/nexus.log") if not cfg.debug else None,
)

APP_ROOT = Path(__file__).resolve().parents[3] / "products" / "desktop" / "ui"

_session_auth: SessionAuth | None = None
_latest_metrics: dict[str, Any] = {}
_latest_alerts: list[dict[str, Any]] = []


def _get_desktop_local_state() -> DesktopLocalState:
    return DesktopLocalState(DesktopSettings.from_env())


def _load_desktop_provider_config() -> DesktopLLMProviderConfig:
    return _get_desktop_local_state().load_llm_provider_config()


def _apply_desktop_provider_config() -> DesktopLLMProviderConfig:
    provider_config = _load_desktop_provider_config()
    apply_desktop_provider_to_cfg(cfg, provider_config)
    return provider_config


if cfg.is_desktop:
    _apply_desktop_provider_config()


def get_session_auth() -> SessionAuth:
    if _session_auth is None:
        raise RuntimeError("SessionAuth no inicializado")
    return _session_auth


def get_current_user(request: Request) -> str | None:
    token = request.cookies.get("session_token")
    if not token:
        return None
    return get_session_auth().verificar_sesion(token)


def require_user(request: Request) -> str:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    return user


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _session_auth

    logger.info(
        "Open-Nexus Desktop backend arrancando | version={} | contexto={}",
        cfg.app_version,
        cfg.nexus_context,
    )

    _session_auth = SessionAuth(cfg)
    logger.info("Desktop lifespan | SessionAuth listo")
    app.state.session_auth = _session_auth
    app.state.conversations = None
    if getattr(app.state, "nexus_runtime", None) is None:
        logger.info("Desktop lifespan | construyendo runtime")
        app.state.nexus_runtime = build_runtime(cfg)
        logger.info("Desktop lifespan | runtime construido")

    from agents.llm_router import get_router
    from agents.prospecting_campaign_agent import ProspectingCampaignAgent
    from nexus.workers.scheduler import NexusScheduler

    logger.info("Desktop lifespan | importes auxiliares listos")
    app.state.llm_router = get_router()
    logger.info("Desktop lifespan | router listo")
    upgrade_runtime_with_app_state(app, cfg)
    logger.info("Desktop lifespan | runtime actualizado")

    # ── Campaña diaria de prospección ────────────────────────────────────────
    runtime = app.state.nexus_runtime
    campaign_agent = ProspectingCampaignAgent(
        prospecting_svc=runtime.prospecting,
        outreach_mgr=runtime.outreach,
        crm_svc=runtime.crm,
    )
    app.state.campaign_agent = campaign_agent

    scheduler = NexusScheduler()
    scheduler.attach_campaign_agent(campaign_agent)
    scheduler.start()
    app.state.nexus_scheduler = scheduler
    logger.info("Desktop lifespan | scheduler iniciado")

    yield

    logger.info("Open-Nexus Desktop backend apagandose...")
    scheduler.stop()
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


class _DesktopResolveBody(BaseModel):
    user_input: str


class _DesktopProviderConfigBody(BaseModel):
    provider_type: str = "openai_compatible"
    provider_label: str = "Servidor remoto"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = False


class _DesktopMonitoringIntegrationBody(BaseModel):
    integration_id: str | None = None
    kind: str
    name: str
    base_url: str
    enabled: bool = True
    is_default: bool = False
    auth_type: str = "none"
    username: str = ""
    secret_ref: str = ""
    header_name: str = ""
    verify_tls: bool = True
    timeout_seconds: int | None = None
    source: str = "manual"


class _DesktopRdpLaunchBody(BaseModel):
    host: str


_rdp_log_lock = threading.Lock()


def _require_desktop_internal(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        logger.warning(
            "Acceso denegado a endpoint interno | host={} | path={}",
            host,
            request.url.path,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo accesible desde localhost")

    token_requerido = cfg.desktop_internal_token
    if token_requerido:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Endpoint interno requiere Authorization: Bearer <desktop_internal_token>",
            )
        token_recibido = auth_header[len("Bearer ") :]
        if not secrets.compare_digest(token_recibido, token_requerido):
            logger.warning("Token interno incorrecto | path={}", request.url.path)
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Token interno incorrecto")


async def _reload_desktop_provider_runtime(app: FastAPI) -> DesktopLLMProviderConfig:
    from agents.llm_router import get_router, reset_router

    provider_config = _apply_desktop_provider_config()
    await reset_router()
    app.state.llm_router = get_router()
    app.state.nexus_runtime = build_runtime(cfg)
    upgrade_runtime_with_app_state(app, cfg)
    return provider_config


async def _reload_desktop_monitoring_runtime(app: FastAPI) -> None:
    app.state.nexus_runtime = build_runtime(cfg)
    upgrade_runtime_with_app_state(app, cfg)


def _get_monitoring_store() -> DesktopMonitoringIntegrationStore:
    return DesktopMonitoringIntegrationStore(
        DesktopSettings.from_env().monitoring_config_db_path
    )


def _get_desktop_settings() -> DesktopSettings:
    return DesktopSettings.from_env()


def _rdp_session_log_path() -> Path:
    state = _get_desktop_local_state()
    state.ensure_layout()
    return state.logs_dir / "rdp_sessions.jsonl"


def _append_rdp_session_log(payload: dict[str, Any]) -> None:
    path = _rdp_session_log_path()
    with _rdp_log_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _watch_rdp_process(process: subprocess.Popen[Any], session_id: str, host: str, pid: int) -> None:
    try:
        exit_code = process.wait()
        finished_at = datetime.now().isoformat()
        logger.info(
            "Sesion RDP terminada | session_id={} | host={} | pid={} | exit_code={}",
            session_id,
            host,
            pid,
            exit_code,
        )
        _append_rdp_session_log(
            {
                "event": "ended",
                "session_id": session_id,
                "host": host,
                "pid": pid,
                "exit_code": exit_code,
                "finished_at": finished_at,
            }
        )
    except Exception as exc:
        logger.warning(
            "No se pudo observar el cierre de la sesion RDP | session_id={} | host={} | error={}",
            session_id,
            host,
            exc,
        )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/open-nexus", status_code=status.HTTP_302_FOUND)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@app.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
):
    auth = get_session_auth()
    if not auth.verificar_credenciales(username, password):
        logger.warning("Login fallido desktop | usuario={}", username)
        return RedirectResponse(
            url="/login?error=Credenciales incorrectas",
            status_code=status.HTTP_302_FOUND,
        )

    token = auth.crear_sesion(username)
    response = RedirectResponse(url="/open-nexus", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=cfg.session_secure_cookie,
        samesite="lax",
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        get_session_auth().cerrar_sesion(token)
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response


@app.get("/health")
async def health():
    auth = get_session_auth()
    return {
        "status": "ok",
        "version": cfg.app_version,
        "redis": False,
        "mongodb": False,
        "sessions": auth.sesiones_activas() if auth else 0,
        "context": cfg.nexus_context,
        "backend": "desktop",
    }


@app.get("/favicon.ico")
async def favicon():
    icon_path = resolve_branding_icon()
    if icon_path is not None:
        return FileResponse(icon_path, media_type="image/x-icon")
    return Response(content=b"", media_type="image/x-icon")


@app.get("/api/metrics")
async def get_metrics(request: Request):
    require_user(request)
    return {
        "available": True,
        "metrics": _latest_metrics,
        "alerts": _latest_alerts,
    }


@app.get("/metrics")
async def prometheus_metrics() -> Response:
    from nexus.outreach.campaign_metrics import update_campaign_metrics

    runtime = getattr(app.state, "nexus_runtime", None)
    if runtime is not None:
        try:
            collectors = await runtime.coordinator.get_collector_status()
            update_collector_metrics(collectors)
        except Exception as exc:
            logger.warning("No se pudo refrescar metricas de recolectores | error={}", exc)

    llm_router = getattr(app.state, "llm_router", None)
    if llm_router is not None:
        try:
            update_llm_router_metrics(llm_router.metrics_snapshot())
        except Exception as exc:
            logger.warning("No se pudo refrescar metricas del router LLM | error={}", exc)

    # Métricas de campañas outreach
    if runtime is not None:
        try:
            scheduler = getattr(app.state, "nexus_scheduler", None)
            await update_campaign_metrics(
                runtime.outreach._repository,
                scheduler=scheduler,
            )
        except Exception as exc:
            logger.warning("No se pudo refrescar metricas de campañas | error={}", exc)

    update_desktop_bridge_metrics(_latest_metrics, _latest_alerts)
    return Response(
        content=metrics_response_body(),
        media_type=metrics_response_content_type(),
    )


@app.get("/api/desktop/runtime")
async def get_desktop_runtime():
    runtime = get_current_runtime()
    if runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Desktop runtime no disponible",
        )
    return {"available": True, "runtime": runtime.describe()}


@app.get("/api/desktop/settings/summary")
async def get_desktop_settings_summary():
    settings = _get_desktop_settings()
    state = _get_desktop_local_state()
    store = _get_monitoring_store()
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
            "config_dir": str(state.config_dir),
            "logs_dir": str(state.logs_dir),
            "history_dir": str(state.history_dir),
            "provider_file": str(state.llm_provider_config_path),
            "monitoring_db": str(settings.monitoring_config_db_path),
        },
        "monitoring": {
            "total_integrations": len(integrations),
            "by_kind": by_kind,
        },
    }


@app.get("/api/desktop/providers")
async def get_desktop_provider_config():
    provider_config = _load_desktop_provider_config()
    return {
        "available": True,
        "provider": provider_config.to_dict(mask_secret=True),
        "configured": provider_config.is_configured,
        "applied": provider_config.enabled and provider_config.is_configured,
    }


@app.put("/api/desktop/providers")
async def save_desktop_provider_config(request: Request, body: _DesktopProviderConfigBody):
    state = _get_desktop_local_state()
    existing_config = state.load_llm_provider_config()
    incoming = body.model_dump()
    if not incoming.get("api_key"):
        incoming["api_key"] = existing_config.api_key

    saved_config = state.save_llm_provider_config(
        DesktopLLMProviderConfig.from_dict(incoming)
    )
    applied_config = await _reload_desktop_provider_runtime(request.app)
    return {
        "available": True,
        "status": "saved",
        "provider": saved_config.to_dict(mask_secret=True),
        "applied": applied_config.enabled and applied_config.is_configured,
        "paths": {
            "config_dir": str(state.config_dir),
            "provider_file": str(state.llm_provider_config_path),
        },
    }


@app.get("/api/desktop/operator/integrations")
async def list_desktop_monitoring_integrations():
    store = _get_monitoring_store()
    store.migrate_from_cfg(cfg)
    integrations = [item.to_dict() for item in store.list_integrations()]
    return {
        "available": True,
        "integrations": integrations,
        "defaults": {
            kind: (store.get_default(kind).integration_id if store.get_default(kind) else None)
            for kind in ("prometheus", "grafana", "alertmanager")
        },
        "paths": {
            "config_db": str(DesktopSettings.from_env().monitoring_config_db_path),
        },
    }


@app.put("/api/desktop/operator/integrations")
async def save_desktop_monitoring_integration(
    request: Request,
    body: _DesktopMonitoringIntegrationBody,
):
    store = _get_monitoring_store()
    integration = DesktopMonitoringIntegration.create(
        integration_id=body.integration_id,
        kind=body.kind,
        name=body.name,
        base_url=body.base_url,
        enabled=body.enabled,
        is_default=body.is_default,
        auth_type=body.auth_type,
        username=body.username,
        secret_ref=body.secret_ref,
        header_name=body.header_name,
        verify_tls=body.verify_tls,
        timeout_seconds=body.timeout_seconds,
        source=body.source,
    )
    saved = store.save_integration(integration)
    await _reload_desktop_monitoring_runtime(request.app)
    return {
        "available": True,
        "status": "saved",
        "integration": saved.to_dict(),
        "paths": {
            "config_db": str(DesktopSettings.from_env().monitoring_config_db_path),
        },
    }


@app.post("/api/desktop/operator/integrations/test")
async def test_desktop_monitoring_integration(body: _DesktopMonitoringIntegrationBody):
    timeout_seconds = body.timeout_seconds or cfg.connector_timeout_seconds
    base_url = body.base_url.strip().rstrip("/")

    if body.kind == "prometheus":
        connector = PrometheusConnector(base_url, timeout_seconds=timeout_seconds)
    elif body.kind == "grafana":
        connector = GrafanaConnector(base_url, timeout_seconds=timeout_seconds)
    elif body.kind == "alertmanager":
        connector = AlertmanagerConnector(base_url, timeout_seconds=timeout_seconds)
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Test de conectividad no soportado todavia para este tipo",
        )

    try:
        report = await connector.healthcheck()
        return {"available": True, "status": "ok", "report": report}
    except Exception as exc:
        return {
            "available": True,
            "status": "error",
            "report": {
                "name": body.name,
                "kind": body.kind,
                "endpoint": base_url,
                "reason": str(exc),
            },
        }


@app.delete("/api/desktop/operator/integrations/{integration_id}")
async def delete_desktop_monitoring_integration(
    request: Request,
    integration_id: str,
):
    store = _get_monitoring_store()
    deleted = store.delete_integration(integration_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integracion no encontrada")
    await _reload_desktop_monitoring_runtime(request.app)
    return {"available": True, "status": "deleted", "integration_id": integration_id}


@app.post("/api/desktop/resolve")
async def resolve_desktop_skill(body: _DesktopResolveBody):
    runtime = get_current_runtime()
    if runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Desktop runtime no disponible",
        )
    return {"available": True, "resolution": runtime.resolve_user_input(body.user_input)}


@app.post("/api/metrics/ingest")
async def ingest_metrics(request: Request):
    _require_desktop_internal(request)
    global _latest_metrics, _latest_alerts
    body = await request.json()
    _latest_metrics = body.get("metrics", {})
    _latest_alerts = body.get("alerts", [])
    return {"status": "ok"}


@app.post("/api/quick-action")
async def quick_action(request: Request):
    _require_desktop_internal(request)
    body = await request.json()
    action = body.get("action", "")

    if action not in ("fichar_entrada", "fichar_salida"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Accion desconocida: {action}")

    task_id = str(uuid.uuid4())
    logger.info("Quick action aceptada en desktop | action={} | task_id={}", action, task_id)
    return {
        "status": "ok",
        "message": (
            "Fichaje de entrada en proceso"
            if action == "fichar_entrada"
            else "Fichaje de salida en proceso"
        ),
        "task_id": task_id,
        "queued": False,
        "source": "desktop_backend",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/desktop/operator/rdp")
async def launch_desktop_rdp(body: _DesktopRdpLaunchBody):
    host = body.host.strip()
    if not host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Debes indicar una IP")

    try:
        parsed_host = ipaddress.ip_address(host).compressed
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "IP no valida") from exc

    session_id = f"rdp-{uuid.uuid4().hex[:12]}"
    started_at = datetime.now().isoformat()

    try:
        process = subprocess.Popen(["mstsc.exe", f"/v:{parsed_host}"], shell=False)
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Cliente RDP no disponible en este equipo",
        ) from exc
    except Exception as exc:
        logger.exception(
            "No se pudo lanzar la sesion RDP | session_id={} | host={}",
            session_id,
            parsed_host,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"No se pudo abrir el cliente RDP: {exc}",
        ) from exc

    logger.info(
        "Sesion RDP iniciada | session_id={} | host={} | pid={}",
        session_id,
        parsed_host,
        process.pid,
    )
    _append_rdp_session_log(
        {
            "event": "started",
            "session_id": session_id,
            "host": parsed_host,
            "pid": process.pid,
            "started_at": started_at,
        }
    )

    watcher = threading.Thread(
        target=_watch_rdp_process,
        args=(process, session_id, parsed_host, process.pid),
        daemon=True,
        name=f"rdp-watch-{session_id}",
    )
    watcher.start()

    return {
        "available": True,
        "status": "launched",
        "session_id": session_id,
        "host": parsed_host,
        "pid": process.pid,
        "started_at": started_at,
        "log_path": str(_rdp_session_log_path()),
    }
