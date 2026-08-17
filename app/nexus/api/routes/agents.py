"""Routes for the server-resident Nexus agent layer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from nexus.agents import get_default_agent_registry
from nexus.agents.shared.result import AgentRun
from nexus.api.dependencies.auth import get_agent_runtime, get_agent_settings_store, get_coordinator
from nexus.api.schemas.agents import (
    AgentCatalogContracts,
    AgentCatalogResponse,
    AgentRunCreateRequest,
    AgentRunListResponse,
)
from nexus.application.services.agent_runtime_service import AgentRuntimeService
from nexus.orchestration.coordinator import NexusCoordinator

router = APIRouter()


@router.get("/agents/catalog", response_model=AgentCatalogResponse)
async def get_agent_catalog(
    surface: str | None = Query(default=None, pattern="^(desktop|web|api)?$"),
) -> AgentCatalogResponse:
    """Expose the shared server-side agent catalog for all surfaces.

    Fusiona el registro formal (Supervisor/Operator/Shell/Sales, con
    BaseServerAgent) con los manifests estaticos de los agentes locales de
    PEPO (desktop.local_agents.manifest) — mismo modelo AgentManifest para
    ambos, un unico catalogo para cualquier UI que lo consuma.
    """
    from desktop.local_agents.manifest import LOCAL_AGENT_MANIFESTS

    registry = get_default_agent_registry()
    agents = list(registry.list_manifests(surface=surface))
    agents.extend(
        manifest for manifest in LOCAL_AGENT_MANIFESTS
        if surface is None or surface in manifest.supported_surfaces
    )
    return AgentCatalogResponse(
        contracts=AgentCatalogContracts(
            request_model="nexus.agents.shared.result.AgentRequest",
            run_model="nexus.agents.shared.result.AgentRun",
            manifest_model="nexus.agents.shared.result.AgentManifest",
            plan_step_model="nexus.agents.shared.result.PlanStep",
            skill_call_model="nexus.agents.shared.result.SkillCall",
        ),
        agents=agents,
    )


@router.get("/agents/runs", response_model=AgentRunListResponse)
async def list_agent_runs(
    surface: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    agent_runtime: AgentRuntimeService = Depends(get_agent_runtime),
) -> AgentRunListResponse:
    """List shared server-side runs for desktop and web consumers."""
    runs = agent_runtime.list_runs(source_surface=surface, agent_id=agent_id)
    return AgentRunListResponse(total=len(runs), runs=runs)


@router.post("/agents/runs", response_model=AgentRun)
async def create_agent_run(
    payload: AgentRunCreateRequest,
    agent_runtime: AgentRuntimeService = Depends(get_agent_runtime),
) -> AgentRun:
    """Bootstrap one server-resident run using the shared agent registry."""
    try:
        return agent_runtime.create_run(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agente no encontrado: {exc.args[0]}") from exc


@router.get("/agents/runs/{run_id}", response_model=AgentRun)
async def get_agent_run(
    run_id: str,
    agent_runtime: AgentRuntimeService = Depends(get_agent_runtime),
) -> AgentRun:
    """Return one shared run by id."""
    run = agent_runtime.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run no encontrado")
    return run


# ── Permisos/activacion por skill (gestor de agentes) ───────────────────────
# Override persistido encima de los defaults hardcodeados en
# DesktopSkillRouter — ver desktop/runtime/agent_settings.py.


class AgentSettingUpdate(BaseModel):
    enabled: bool | None = None
    permission_level: int | None = None


@router.get("/agents/settings")
async def get_agent_settings(
    store: Any = Depends(get_agent_settings_store),
) -> dict[str, Any]:
    if store is None:
        return {"status": "unavailable", "settings": {}}
    return {"status": "ok", "settings": store.load()}


@router.put("/agents/settings/{skill_id}")
async def update_agent_setting(
    skill_id: str,
    payload: AgentSettingUpdate,
    store: Any = Depends(get_agent_settings_store),
) -> dict[str, Any]:
    if store is None:
        raise HTTPException(status_code=503, detail="Gestor de agentes no disponible en este runtime.")
    updated = store.set_override(skill_id, enabled=payload.enabled, permission_level=payload.permission_level)
    return {"status": "ok", "skill_id": skill_id, "setting": updated}


# ── Acciones pendientes unificadas (gestor de agentes) ──────────────────────
# Mismo estado que ya usa el chat de PEPO (has_pending/confirm/cancel por
# context_id) — confirmar/cancelar desde aqui o desde el chat es equivalente.


class PendingActionConfirm(BaseModel):
    user_reply: str | None = None


@router.get("/agents/pending")
async def list_pending_actions(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, Any]:
    pending = await coordinator.list_pending_actions()
    return {"status": "ok", "total": len(pending), "pending": pending}


@router.post("/agents/pending/{context_id}/confirm")
async def confirm_pending_action(
    context_id: str,
    payload: PendingActionConfirm | None = None,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, Any]:
    user_reply = payload.user_reply if payload else None
    result = await coordinator.confirm_pending_action(context_id, user_reply)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="No hay ninguna accion pendiente con ese context_id")
    return result


@router.post("/agents/pending/{context_id}/cancel")
async def cancel_pending_action(
    context_id: str,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, Any]:
    result = await coordinator.cancel_pending_action(context_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="No hay ninguna accion pendiente con ese context_id")
    return result
