"""Autenticación por sesión de Desktop: login/logout + dependencias de auth.

`get_session_auth` lee `request.app.state.session_auth` (poblado una vez en
`lifespan()`, ver `app.py`) en vez de un global de módulo — mismo patrón que
`app.state.nexus_runtime`/`app.state.llm_router`, sin un global adicional
que sincronizar entre módulos.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from loguru import logger

from config import cfg
from utils.session_auth import SessionAuth

router = APIRouter()


def get_session_auth(request: Request) -> SessionAuth:
    auth = getattr(request.app.state, "session_auth", None)
    if auth is None:
        raise RuntimeError("SessionAuth no inicializado")
    return auth


def get_current_user(request: Request) -> str | None:
    token = request.cookies.get("session_token")
    if not token:
        return None
    return get_session_auth(request).verificar_sesion(token)


def require_user(request: Request) -> str:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    return user


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    auth = get_session_auth(request)
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: auth.verificar_credenciales(username, password))
    if not ok:
        logger.warning("Login fallido desktop | usuario={}", username)
        return RedirectResponse(
            url="/login?error=Credenciales incorrectas",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    token = auth.crear_sesion(username)
    response = RedirectResponse(url="/open-nexus", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=cfg.session_secure_cookie,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        get_session_auth(request).cerrar_sesion(token)
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response
