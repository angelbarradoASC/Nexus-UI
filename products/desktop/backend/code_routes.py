"""Ajustes del modo codigo de PEPO — carpetas de trabajo autorizadas (Desktop-only).

El agente de codigo SOLO trabaja en carpetas de esta lista (ver
desktop/storage/code_settings.py y docs/PLAN_PEPO_MODO_CODIGO.md, D4). Estos
endpoints son lo unico que la modifica; el chat nunca puede ampliarla.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from pydantic import BaseModel, Field

from desktop.code_agent.workspace import WorkspaceError
from desktop.config import DesktopSettings
from desktop.storage.code_settings import (
    DEFAULT_NUM_CTX,
    MAX_NUM_CTX,
    MAX_TOKENS_PER_MINUTE,
    MIN_NUM_CTX,
    MIN_TOKENS_PER_MINUTE,
    CodeSettingsStore,
)
from products.desktop.backend.dependencies import get_desktop_settings

router = APIRouter(prefix="/api/desktop/code", tags=["desktop-code"])


def get_code_settings_store(settings: DesktopSettings = Depends(get_desktop_settings)) -> CodeSettingsStore:
    return CodeSettingsStore(settings.code_settings_path)


class _PathBody(BaseModel):
    path: str


class _EnabledBody(BaseModel):
    enabled: bool


class _ModelBody(BaseModel):
    base_url: str = ""
    model: str = ""
    num_ctx: int = Field(default=DEFAULT_NUM_CTX, ge=MIN_NUM_CTX, le=MAX_NUM_CTX)
    think: bool = False


class _LimitsBody(BaseModel):
    tokens_per_minute: int = Field(ge=MIN_TOKENS_PER_MINUTE, le=MAX_TOKENS_PER_MINUTE)


def _view(store: CodeSettingsStore) -> dict:
    data = store.load()
    return {
        "enabled": data["enabled"],
        "tokens_per_minute": data["tokens_per_minute"],
        "llm": data["llm"],
        "workspaces": [
            {"path": item, "name": Path(item).name or item, "exists": Path(item).is_dir()}
            for item in data["workspaces"]
        ],
    }


@router.get("/settings")
def get_code_settings(store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    return _view(store)


@router.post("/workspaces")
def add_workspace(body: _PathBody, store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    try:
        store.add_workspace(body.path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _view(store)


@router.post("/workspaces/remove")
def remove_workspace(body: _PathBody, store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    store.remove_workspace(body.path)
    return _view(store)


@router.put("/limits")
def set_limits(body: _LimitsBody, store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    store.set_tokens_per_minute(body.tokens_per_minute)
    return _view(store)


@router.put("/model")
def set_model(body: _ModelBody, store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    """Modelo propio del agente (Ollama). Con URL y modelo vacios vuelve al router de siempre."""
    try:
        store.set_llm(body.base_url, body.model, body.num_ctx, body.think)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _view(store)


@router.post("/model/test")
def test_model(store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    """Comprueba que el Ollama configurado responde y que el modelo esta descargado."""
    llm = store.llm()
    if not llm:
        return {"ok": False, "detail": "No hay modelo propio configurado: el agente usa el router de siempre."}
    try:
        reply = httpx.get(f"{llm['base_url']}/api/tags", timeout=8.0)
        names = [m.get("name", "") for m in reply.json().get("models", [])]
    except Exception as exc:
        return {"ok": False, "detail": f"No responde {llm['base_url']}: {type(exc).__name__}"}
    if llm["model"] not in names:
        return {"ok": False, "detail": f"Ollama responde pero el modelo {llm['model']} no esta descargado.", "available": names}
    return {"ok": True, "detail": f"Ollama responde y {llm['model']} esta disponible.", "available": names}


@router.put("/enabled")
def set_enabled(body: _EnabledBody, store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    store.set_enabled(body.enabled)
    return _view(store)
