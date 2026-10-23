"""
products/desktop/backend/obsidian_routes.py
----------------------------------------------
Ajustes del asistente de Obsidian de PEPO y repaso de la boveda (docs/PLAN_PEPO_OBSIDIAN.md).

La boveda la valida `ObsidianSettingsStore` (debe tener `.obsidian`): nunca se confia en una ruta que llegue
del cliente sin pasar por ahi.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from desktop.code_agent.workspace import WorkspaceError
from desktop.config import DesktopSettings
from desktop.obsidian.assistant import ObsidianAssistant
from desktop.obsidian.audit import format_report
from desktop.storage.obsidian_settings import ObsidianSettingsStore
from products.desktop.backend.dependencies import get_desktop_settings

router = APIRouter(prefix="/api/desktop/obsidian", tags=["desktop-obsidian"])


def get_obsidian_settings_store(settings: DesktopSettings = Depends(get_desktop_settings)) -> ObsidianSettingsStore:
    return ObsidianSettingsStore(settings.obsidian_settings_path)


class _VaultBody(BaseModel):
    path: str = ""


class _EnabledBody(BaseModel):
    enabled: bool


def _view(store: ObsidianSettingsStore) -> dict:
    data = store.load()
    path, source = store.effective_vault()
    return {
        "enabled": data["enabled"],
        "configured": data["vault"],
        "vault": {"path": str(path), "name": path.name, "source": source} if path else None,
    }


@router.get("/settings")
def get_settings(store: ObsidianSettingsStore = Depends(get_obsidian_settings_store)) -> dict:
    return _view(store)


@router.put("/vault")
def set_vault(body: _VaultBody, store: ObsidianSettingsStore = Depends(get_obsidian_settings_store)) -> dict:
    """Fija la boveda (debe contener `.obsidian`). Con la ruta vacia vuelve a usar la abierta en Obsidian."""
    try:
        store.set_vault(body.path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _view(store)


@router.put("/enabled")
def set_enabled(body: _EnabledBody, store: ObsidianSettingsStore = Depends(get_obsidian_settings_store)) -> dict:
    store.set_enabled(body.enabled)
    return _view(store)


@router.get("/audit")
def audit(store: ObsidianSettingsStore = Depends(get_obsidian_settings_store)) -> dict:
    """Repaso de la boveda: informe en texto y recuentos. Solo lectura."""
    vault = ObsidianAssistant(store).open_vault()
    if isinstance(vault, str):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=vault)
    report = ObsidianAssistant.build_report(vault)
    return {
        "text": format_report(report),
        "counts": {
            "notes": report.notes, "links": report.links, "broken": len(report.broken), "ambiguous": len(report.ambiguous),
            "empty": len(report.empty), "orphans": len(report.orphans), "duplicates": len(report.duplicate_titles),
            "mentions": len(report.mentions), "no_frontmatter": len(report.no_frontmatter),
        },
        "vault": Path(vault.root).name,
    }
