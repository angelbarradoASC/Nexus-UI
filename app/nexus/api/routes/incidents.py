"""Incident ingestion and tracking routes for Nexus v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nexus.api.dependencies.auth import get_coordinator
from nexus.api.schemas.incidents import (
    IncidentActionRequest,
    IncidentIngestRequest,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdateRequest,
)
from nexus.orchestration.coordinator import NexusCoordinator

router = APIRouter()


@router.post("/incidents", response_model=IncidentResponse)
async def ingest_incident(
    payload: IncidentIngestRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> IncidentResponse:
    """Incident intake for Nexus v1."""
    return await coordinator.handle_incident(payload)


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> IncidentListResponse:
    """Recent incidents for the operational UI."""
    return await coordinator.list_incidents()


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    """Retrieve one incident by id."""
    result = await coordinator.get_incident(incident_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.patch("/incidents/{incident_id}")
async def update_incident(
    incident_id: str,
    payload: IncidentUpdateRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    """Update incident lifecycle state."""
    result = await coordinator.update_incident(
        incident_id,
        status=payload.status,
        actor=payload.actor,
        owner=payload.owner,
        resolution_note=payload.resolution_note,
    )
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.post("/incidents/{incident_id}/actions")
async def execute_incident_action(
    incident_id: str,
    payload: IncidentActionRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    """Preview or execute a runbook-linked incident action."""
    result = await coordinator.execute_incident_action(
        incident_id,
        action_name=payload.action_name,
        actor=payload.actor,
        dry_run=payload.dry_run,
    )
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Incident not found")
    if result["status"] == "blocked":
        raise HTTPException(status_code=409, detail=result["reason"])
    return result
