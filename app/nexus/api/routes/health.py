"""Health and readiness routes for Nexus v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nexus.api.dependencies.auth import get_coordinator
from nexus.orchestration.coordinator import NexusCoordinator

router = APIRouter()


@router.get("/health")
async def nexus_v1_health(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    """Health endpoint for the Nexus v1 surface."""
    return await coordinator.health_snapshot()
