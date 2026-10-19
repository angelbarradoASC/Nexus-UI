"""Ajustes del modo codigo de PEPO — carpetas de trabajo autorizadas (Desktop-only).

El agente de codigo SOLO trabaja en carpetas de esta lista (ver
desktop/storage/code_settings.py y docs/PLAN_PEPO_MODO_CODIGO.md, D4). Estos
endpoints son lo unico que la modifica; el chat nunca puede ampliarla.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from desktop.code_agent.workspace import WorkspaceError
from desktop.config import DesktopSettings
from desktop.storage.code_settings import MAX_TOKENS_PER_MINUTE, MIN_TOKENS_PER_MINUTE, CodeSettingsStore
from products.desktop.backend.dependencies import get_desktop_settings

router = APIRouter(prefix="/api/desktop/code", tags=["desktop-code"])


def get_code_settings_store(settings: DesktopSettings = Depends(get_desktop_settings)) -> CodeSettingsStore:
    return CodeSettingsStore(settings.code_settings_path)


class _PathBody(BaseModel):
    path: str


class _EnabledBody(BaseModel):
    enabled: bool


class _LimitsBody(BaseModel):
    tokens_per_minute: int = Field(ge=MIN_TOKENS_PER_MINUTE, le=MAX_TOKENS_PER_MINUTE)


def _view(store: CodeSettingsStore) -> dict:
    data = store.load()
    return {
        "enabled": data["enabled"],
        "tokens_per_minute": data["tokens_per_minute"],
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


@router.put("/enabled")
def set_enabled(body: _EnabledBody, store: CodeSettingsStore = Depends(get_code_settings_store)) -> dict:
    store.set_enabled(body.enabled)
    return _view(store)
