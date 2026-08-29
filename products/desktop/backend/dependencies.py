"""Dependencias FastAPI compartidas entre los routers de Desktop.

`get_desktop_settings`/`get_desktop_local_state` leen la instancia cacheada
en `app.state` (construida una vez en `lifespan()`, ver `app.py`) en vez de
reconstruir `DesktopSettings.from_env()`/`DesktopLocalState` en cada
petición — antes cada handler llamaba a un helper que las creaba desde cero.
"""

from __future__ import annotations

import secrets

import config as config_module
from fastapi import HTTPException, Request, status
from loguru import logger

from desktop.storage.local_state import DesktopLocalState
from desktop.config import DesktopSettings


def get_desktop_settings(request: Request) -> DesktopSettings:
    return request.app.state.desktop_settings


def get_desktop_local_state(request: Request) -> DesktopLocalState:
    return request.app.state.desktop_local_state


def require_desktop_internal(request: Request) -> None:
    """Guard de los endpoints internos (ingesta de métricas, quick-action):
    solo localhost, y con token si `desktop_internal_token` está configurado."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        logger.warning(
            "Acceso denegado a endpoint interno | host={} | path={}",
            host,
            request.url.path,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo accesible desde localhost")

    # Se lee config_module.cfg (no un `cfg` importado por valor) para no
    # quedarse con una referencia obsoleta si algun test recarga config.py
    # sin recargar tambien este modulo.
    token_requerido = config_module.cfg.desktop_internal_token
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
