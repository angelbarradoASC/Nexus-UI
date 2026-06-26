"""
app/main.py
-----------
FastAPI app factory para NEXUS-UI.

Responsabilidades:
  - Montar la app y registrar routers / handlers
  - Gestionar el ciclo de vida (lifespan): conexiones, cleanup
  - Rutas de auth (login/logout) y principales (chat, historial)
  - Endpoints Desktop API (/api/metrics, /api/quick-action)

No contiene lógica de negocio — delega en servicios y agentes.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Form, HTTPException, Request, status
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from config import cfg
from db import ConversationRepository
from exceptions import register_exception_handlers
from nexus.api.dependencies.auth import upgrade_runtime_with_app_state
from nexus.api.schemas.monitoring import AlertWebhookRequest
from nexus.bootstrap import register_nexus_v1
from utils.logger import setup_logging
from utils.session_auth import SessionAuth
from desktop.config import DesktopSettings
from desktop.runtime.llm_provider_runtime import apply_desktop_provider_to_cfg
from desktop.runtime.bootstrap import get_current_runtime
from desktop.storage.local_state import DesktopLocalState
from desktop.storage.monitoring_integrations import DesktopMonitoringIntegrationStore
from desktop.storage.provider_config import DesktopLLMProviderConfig
from metrics import (
    metrics_response_body,
    metrics_response_content_type,
    update_collector_metrics,
    update_desktop_bridge_metrics,
    update_llm_router_metrics,
)

# ── Logging — primera acción antes de cualquier import de app ─────────────────
setup_logging(
    nivel=cfg.log_level,
    archivo=Path("logs/nexus.log"),
)

APP_DIR = Path(__file__).resolve().parent

# ── Estado global de la aplicación (inicializado en lifespan) ─────────────────
_redis: aioredis.Redis | None = None
_session_auth: SessionAuth | None = None
_latest_metrics: dict[str, Any] = {}
_latest_alerts: list[dict] = []
_rdp_log_lock = threading.Lock()


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


def _get_monitoring_store() -> DesktopMonitoringIntegrationStore:
    return DesktopMonitoringIntegrationStore(
        DesktopSettings.from_env().monitoring_config_db_path
    )


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


# ── Helpers de acceso al estado ───────────────────────────────────────────────

def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Redis no disponible")
    return _redis


def get_session_auth() -> SessionAuth:
    if _session_auth is None:
        raise RuntimeError("SessionAuth no inicializado")
    return _session_auth


def get_current_user(request: Request) -> str | None:
    """Devuelve el username de la sesión activa, o None."""
    token = request.cookies.get("session_token")
    if not token:
        return None
    return get_session_auth().verificar_sesion(token)


def require_user(request: Request) -> str:
    """Como get_current_user pero lanza 401 si no hay sesión."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    return user


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _session_auth

    logger.info("NEXUS-UI arrancando | versión={} | contexto={}", cfg.app_version, cfg.nexus_context)

    # ── SessionAuth (bcrypt en arranque) ──────────────────────────────────
    _session_auth = SessionAuth(cfg)

    # ── Redis async ───────────────────────────────────────────────────────
    try:
        _redis = aioredis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            db=cfg.redis_db,
            password=cfg.redis_password or None,
            decode_responses=True,
        )
        await _redis.ping()
        logger.info("Redis conectado | {}:{}", cfg.redis_host, cfg.redis_port)
    except Exception as e:
        logger.error("Redis no disponible | error={}", e)
        _redis = None

    # ── MongoDB (sync encapsulado — motor upgrade en Phase 2) ─────────────
    if cfg.mongo_uri:
        try:
            from pymongo import MongoClient
            _mongo_client = MongoClient(cfg.mongo_uri, serverSelectionTimeoutMS=5000)
            await asyncio.to_thread(_mongo_client.admin.command, "ping")
            app.state.conversations = _mongo_client[cfg.mongo_db_name].conversations
            logger.info("MongoDB conectado | db={}", cfg.mongo_db_name)
        except Exception as e:
            logger.error("MongoDB no disponible | error={}", e)
            app.state.conversations = None
    else:
        logger.warning("MONGO_URI no configurado — historial deshabilitado")
        app.state.conversations = None

    # ── LLMRouter AsyncClient ─────────────────────────────────────────────
    from agents.llm_router import get_router
    app.state.llm_router = get_router()
    app.state.repo = ConversationRepository(app.state.conversations)
    upgrade_runtime_with_app_state(app, cfg)

    yield  # ── App corriendo ───────────────────────────────────────────────

    # ── Cleanup al apagar ─────────────────────────────────────────────────
    logger.info("NEXUS-UI apagándose...")
    if _redis:
        await _redis.aclose()
    await app.state.llm_router.close()
    logger.info("NEXUS-UI detenido limpiamente")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=cfg.app_name,
    version=cfg.app_version,
    lifespan=lifespan,
    docs_url="/docs" if cfg.debug else None,
    redoc_url=None,
)

register_exception_handlers(app)
register_nexus_v1(app)

# Static files y templates
os.makedirs(APP_DIR / "static", exist_ok=True)
os.makedirs(APP_DIR / "templates", exist_ok=True)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


# ── Rutas de autenticación ────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": error}
    )


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    auth = get_session_auth()

    # bcrypt.checkpw — timing-safe, sin plaintext en logs
    if not auth.verificar_credenciales(username, password):
        logger.warning("Login fallido | usuario={}", username)
        return RedirectResponse(
            url="/login?error=Credenciales incorrectas",
            status_code=status.HTTP_302_FOUND,
        )

    token = auth.crear_sesion(username)
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=cfg.session_secure_cookie,
        samesite="lax",
    )
    logger.info("Login exitoso | usuario={}", username)
    return response


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        get_session_auth().cerrar_sesion(token)
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response


# ── Rutas principales ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "chat.html", {"request": request, "username": current_user}
    )


@app.post("/chat")
async def chat(
    request: Request,
    user_message: str = Form(...),
    selected_agent: str = Form(default="general"),
):
    current_user = require_user(request)
    redis = get_redis()

    # Recuperar historial reciente para dar contexto al LLM (últimos 5 intercambios)
    conversation_history: list[dict[str, str]] = []
    repo = _get_repo()
    if repo.disponible:
        prev_docs = await repo.listar(current_user, limit=5)
        # listar() devuelve orden DESC (más reciente primero) — invertir para el LLM
        for doc in reversed(prev_docs):
            if doc.get("query"):
                conversation_history.append({"role": "user",      "content": doc["query"]})
            if doc.get("response"):
                conversation_history.append({"role": "assistant", "content": doc["response"]})

    # Normalizar override — solo valores válidos pasan al worker
    _valid_overrides = {"analyst", "coder", "researcher"}
    agent_override = selected_agent if selected_agent in _valid_overrides else None

    task_id = str(uuid.uuid4())
    task = {
        "task_id":              task_id,
        "user_query":           user_message,
        "username":             current_user,
        "conversation_history": conversation_history,
        "agent_override":       agent_override,
        "timestamp":            datetime.now().isoformat(),
    }
    await redis.lpush("nexus_tasks", json.dumps(task))
    logger.debug(
        "Chat task encolado | task_id={} | usuario={} | turnos_historial={}",
        task_id, current_user, len(conversation_history) // 2,
    )
    return {"task_id": task_id, "status": "processing"}


@app.get("/check_response/{task_id}")
async def check_response(task_id: str, request: Request):
    require_user(request)
    redis = get_redis()

    result = await redis.rpop(f"nexus_results_{task_id}")
    if result:
        try:
            return {"status": "completed", "data": json.loads(result)}
        except json.JSONDecodeError:
            logger.error("check_response: JSON inválido | task_id={}", task_id)
            return {"status": "error", "message": "Formato de respuesta inválido"}
    return {"status": "processing"}


@app.get("/chat/stream/{task_id}")
async def chat_stream(task_id: str, request: Request):
    """
    SSE endpoint — suscribe al canal Redis nexus_stream:{task_id} y
    retransmite chunks al cliente como Server-Sent Events.

    Eventos emitidos:
      data: {"type": "chunk",  "content": "..."}   — texto parcial
      data: {"type": "done",   "thinking": "...", ...} — fin, con metadata
      data: {"type": "error",  "content": "..."}   — fallo en el worker
    """
    require_user(request)
    redis = get_redis()

    async def _event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"nexus_stream:{task_id}")
        deadline = asyncio.get_event_loop().time() + 180  # 3 min máx

        try:
            while asyncio.get_event_loop().time() < deadline:
                if await request.is_disconnected():
                    break

                message = pubsub.get_message(ignore_subscribe_messages=True)
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    try:
                        data = json.loads(message["data"])
                        if data.get("type") in ("done", "error"):
                            break
                    except json.JSONDecodeError:
                        pass
                else:
                    await asyncio.sleep(0.02)  # 20ms — ~50 checks/s
        finally:
            await pubsub.unsubscribe(f"nexus_stream:{task_id}")
            await pubsub.aclose()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Historial de conversaciones ───────────────────────────────────────────────

def _get_repo() -> ConversationRepository:
    return getattr(app.state, "repo", ConversationRepository(None))


@app.get("/api/history/{username}")
async def get_user_history(request: Request, username: str, limit: int = 10):
    current_user = require_user(request)
    admin = get_session_auth().primer_usuario()

    if current_user != username and current_user != admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permisos")

    repo = _get_repo()
    if not repo.disponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")

    docs = await repo.listar(username, limit=limit)
    conversations = repo.formatear_para_api(docs)
    return {"status": "success", "conversations": conversations, "total": len(conversations), "username": username}


@app.get("/api/conversation/{conversation_id}")
async def get_conversation_detail(request: Request, conversation_id: str):
    current_user = require_user(request)

    repo = _get_repo()
    if not repo.disponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")

    conv = await repo.obtener(conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")

    admin = get_session_auth().primer_usuario()
    if conv.get("username") != current_user and current_user != admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permisos")

    return {"status": "success", "conversation": conv}


class _FolderBody(BaseModel):
    folder: str


class _DesktopResolveBody(BaseModel):
    user_input: str


class _DesktopProviderConfigBody(BaseModel):
    provider_type: str = "openai_compatible"
    provider_label: str = "Servidor remoto"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = False


class _DesktopRdpLaunchBody(BaseModel):
    host: str


@app.delete("/api/conversation/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str):
    """Elimina una conversación. Solo el propietario o el admin pueden borrarla."""
    current_user = require_user(request)

    repo = _get_repo()
    if not repo.disponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")

    # Verificar propiedad antes de borrar
    conv = await repo.obtener(conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")

    admin = get_session_auth().primer_usuario()
    if conv.get("username") != current_user and current_user != admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permisos")

    deleted = await repo.eliminar(conversation_id)
    if not deleted:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al eliminar")

    return {"status": "success", "deleted": conversation_id}


@app.patch("/api/conversation/{conversation_id}/folder")
async def update_conversation_folder(
    request: Request,
    conversation_id: str,
    body: _FolderBody,
):
    """Asigna o cambia la carpeta de una conversación."""
    current_user = require_user(request)

    repo = _get_repo()
    if not repo.disponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")

    conv = await repo.obtener(conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")

    admin = get_session_auth().primer_usuario()
    if conv.get("username") != current_user and current_user != admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permisos")

    updated = await repo.actualizar_carpeta(conversation_id, body.folder)
    if not updated:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al actualizar carpeta")

    return {"status": "success", "conversation_id": conversation_id, "folder": body.folder}


@app.post("/api/conversation/{conversation_id}/favorite")
async def toggle_conversation_favorite(request: Request, conversation_id: str):
    """Alterna el estado de favorito de una conversación."""
    current_user = require_user(request)

    repo = _get_repo()
    if not repo.disponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")

    conv = await repo.obtener(conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")

    admin = get_session_auth().primer_usuario()
    if conv.get("username") != current_user and current_user != admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permisos")

    nuevo_valor = await repo.toggle_favorito(conversation_id)
    if nuevo_valor is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al actualizar favorito")

    return {"status": "success", "conversation_id": conversation_id, "favorite": nuevo_valor}


@app.post("/api/canvas/save")
async def save_canvas(request: Request):
    """Persiste el contenido del Canvas para la conversación activa."""
    current_user = require_user(request)

    body = await request.json()
    conversation_id = body.get("conversation_id", "")
    content         = body.get("content", "")
    canvas_type     = body.get("type", "code")   # "code" | "text" | "diff"

    repo = _get_repo()
    if not repo.disponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible")

    if not conversation_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "conversation_id es obligatorio")

    conv = await repo.obtener(conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")

    admin = get_session_auth().primer_usuario()
    if conv.get("username") != current_user and current_user != admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permisos")

    updated = await repo.guardar_canvas(conversation_id, content, canvas_type)
    if not updated:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error al guardar canvas")

    return {"status": "success", "conversation_id": conversation_id, "type": canvas_type}


# ── Observability proxies ─────────────────────────────────────────────────────

@app.get("/api/alerts")
async def get_alerts(request: Request):
    require_user(request)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{cfg.alertmanager_url}/api/v2/alerts",
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            alerts = resp.json()
            return {"status": "success", "alerts": alerts, "total": len(alerts)}
    except httpx.RequestError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"AlertManager no disponible: {e}")


@app.get("/api/prometheus/query")
async def query_prometheus(request: Request, query: str):
    require_user(request)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{cfg.prometheus_url}/api/v1/query",
                params={"query": query},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Prometheus no disponible: {e}")


@app.post("/api/alerts/silence")
async def silence_alert(
    request: Request,
    alert_id: str = Form(...),
    duration: int = Form(3600),
):
    current_user = require_user(request)
    from datetime import timedelta, timezone
    import httpx

    start_time = datetime.now(timezone.utc)
    end_time   = start_time + timedelta(seconds=duration)
    silence_data = {
        "matchers":  [{"name": "alertname", "value": alert_id, "isRegex": False}],
        "startsAt":  start_time.isoformat(),
        "endsAt":    end_time.isoformat(),
        "createdBy": current_user,
        "comment":   f"Silenciado por {current_user} via NEXUS",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{cfg.alertmanager_url}/api/v2/silences",
                json=silence_data,
            )
            resp.raise_for_status()
            return {"status": "success", "silence_id": resp.json().get("silenceID")}
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error silenciando alerta: {e}")


@app.post("/api/alerts/webhook")
async def alertmanager_webhook(payload: AlertWebhookRequest):
    """Legacy webhook endpoint kept for Alertmanager compatibility."""
    runtime = getattr(app.state, "nexus_runtime", None)
    if runtime is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Nexus runtime not available")
    return await runtime.coordinator.handle_alertmanager_webhook(payload)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    auth = get_session_auth()
    return {
        "status":   "ok",
        "version":  cfg.app_version,
        "redis":    _redis is not None,
        "mongodb":  getattr(app.state, "conversations", None) is not None,
        "sessions": auth.sesiones_activas() if auth else 0,
        "context":  cfg.nexus_context,
    }


@app.get("/favicon.ico")
async def favicon():
    return Response(content=b"", media_type="image/x-icon")


# ── Desktop API ───────────────────────────────────────────────────────────────

def _require_desktop_internal(request: Request) -> None:
    """
    Protege los endpoints internos del tray desktop.

    Estrategia en capas:
      1. Siempre verifica que la petición venga de localhost.
      2. Si DESKTOP_INTERNAL_TOKEN está definido en .env, verifica además
         el header 'Authorization: Bearer <token>'.

    Sin token configurado: solo localhost (aceptable en desarrollo local).
    Con token configurado: localhost + bearer (recomendado en producción desktop).
    """
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        logger.warning(
            "Acceso denegado a endpoint interno | host={} | path={}",
            host, request.url.path,
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
        token_recibido = auth_header[len("Bearer "):]
        import secrets as _secrets
        if not _secrets.compare_digest(token_recibido, token_requerido):
            logger.warning(
                "Token interno incorrecto | path={}", request.url.path
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Token interno incorrecto")


async def _reload_desktop_provider_runtime(app: FastAPI) -> DesktopLLMProviderConfig:
    """
    Reload desktop-local remote provider config and rebuild the Nexus runtime.

    Open-Nexus should be able to change remote model endpoints without
    touching .env files or requiring local model runtimes.
    """
    from agents.llm_router import get_router, reset_router
    from nexus.api.dependencies.auth import build_runtime

    provider_config = _apply_desktop_provider_config()
    await reset_router()
    app.state.llm_router = get_router()
    app.state.nexus_runtime = build_runtime(cfg)
    upgrade_runtime_with_app_state(app, cfg)
    return provider_config


@app.get("/api/metrics")
async def get_metrics(request: Request):
    require_user(request)
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}
    return {"available": True, "metrics": _latest_metrics, "alerts": _latest_alerts}


@app.get("/metrics")
async def prometheus_metrics() -> Response:
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

    update_desktop_bridge_metrics(_latest_metrics, _latest_alerts)
    return Response(
        content=metrics_response_body(),
        media_type=metrics_response_content_type(),
    )


@app.get("/api/desktop/runtime")
async def get_desktop_runtime(request: Request):
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}
    runtime = get_current_runtime()
    if runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Desktop runtime no disponible",
        )
    return {"available": True, "runtime": runtime.describe()}


@app.get("/api/desktop/providers")
async def get_desktop_provider_config(request: Request):
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}
    provider_config = _load_desktop_provider_config()
    return {
        "available": True,
        "provider": provider_config.to_dict(mask_secret=True),
        "configured": provider_config.is_configured,
        "applied": provider_config.enabled and provider_config.is_configured,
    }


@app.get("/api/desktop/operator/integrations")
async def list_desktop_monitoring_integrations(request: Request):
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}

    store = _get_monitoring_store()
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


@app.put("/api/desktop/providers")
async def save_desktop_provider_config(request: Request, body: _DesktopProviderConfigBody):
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}

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


@app.post("/api/desktop/resolve")
async def resolve_desktop_skill(request: Request, body: _DesktopResolveBody):
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}
    runtime = get_current_runtime()
    if runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Desktop runtime no disponible",
        )
    return {"available": True, "resolution": runtime.resolve_user_input(body.user_input)}


@app.post("/api/desktop/operator/rdp")
async def launch_desktop_rdp(request: Request, body: _DesktopRdpLaunchBody):
    if not cfg.is_desktop:
        return {"available": False, "reason": "Solo disponible en Nexus-UI Desktop"}

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


@app.post("/api/metrics/ingest")
async def ingest_metrics(request: Request):
    _require_desktop_internal(request)
    global _latest_metrics, _latest_alerts
    body = await request.json()
    _latest_metrics = body.get("metrics", {})
    _latest_alerts  = body.get("alerts", [])
    return {"status": "ok"}


@app.post("/api/quick-action")
async def quick_action(request: Request):
    _require_desktop_internal(request)
    body = await request.json()
    action = body.get("action", "")

    if action not in ("fichar_entrada", "fichar_salida"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Acción desconocida: {action}")

    redis = None
    try:
        redis = get_redis()
    except HTTPException:
        if not cfg.is_desktop:
            raise

    task_id = str(uuid.uuid4())
    task = {
        "task_id":              task_id,
        "user_query":           action.replace("_", " "),
        "username":             "desktop_tray",
        "conversation_history": [],
        "timestamp":            datetime.now().isoformat(),
        "source":               "quick_action",
    }
    if redis is not None:
        await redis.lpush("nexus_tasks", json.dumps(task))
        logger.info("Quick action encolada | action={} | task_id={}", action, task_id)
    else:
        logger.warning(
            "Quick action aceptada sin Redis | action={} | task_id={}",
            action,
            task_id,
        )
    return {
        "status":  "ok",
        "message": f"{'Fichaje de entrada' if action == 'fichar_entrada' else 'Fichaje de salida'} en proceso",
        "task_id": task_id,
    }
