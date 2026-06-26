"""Audit routes for Nexus v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nexus.api.dependencies.auth import get_coordinator
from nexus.orchestration.coordinator import NexusCoordinator

router = APIRouter()


@router.get("/audit")
async def list_audit(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    """Recent audit entries for the operational UI."""
    return await coordinator.list_audit_entries()
