"""Routes for the server-resident Nexus agent layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from nexus.agents import get_default_agent_registry
from nexus.agents.shared.result import AgentRun
from nexus.api.dependencies.auth import get_agent_runtime
from nexus.api.schemas.agents import (
    AgentCatalogContracts,
    AgentCatalogResponse,
    AgentRunCreateRequest,
    AgentRunListResponse,
)
from nexus.application.services.agent_runtime_service import AgentRuntimeService

router = APIRouter()


@router.get("/agents/catalog", response_model=AgentCatalogResponse)
async def get_agent_catalog(
    surface: str | None = Query(default=None, pattern="^(desktop|web|api)?$"),
) -> AgentCatalogResponse:
    """Expose the shared server-side agent catalog for all surfaces."""
    registry = get_default_agent_registry()
    return AgentCatalogResponse(
        contracts=AgentCatalogContracts(
            request_model="nexus.agents.shared.result.AgentRequest",
            run_model="nexus.agents.shared.result.AgentRun",
            manifest_model="nexus.agents.shared.result.AgentManifest",
            plan_step_model="nexus.agents.shared.result.PlanStep",
            skill_call_model="nexus.agents.shared.result.SkillCall",
        ),
        agents=registry.list_manifests(surface=surface),
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
