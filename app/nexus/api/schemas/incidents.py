"""Incident request and response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IncidentIngestRequest(BaseModel):
    """Incoming incident or alert normalized into the incident pipeline."""

    source: str = Field(default="api")
    title: str = Field(min_length=3)
    severity: str = Field(default="warning")
    fingerprint: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class IncidentResponse(BaseModel):
    """Response returned after Nexus accepts an incident."""

    status: str
    incident_id: str
    severity: str
    normalized: bool
    next_action: str
    runbook: dict[str, Any] = Field(default_factory=dict)
    ticket: dict[str, Any] = Field(default_factory=dict)


class IncidentListResponse(BaseModel):
    """Recent incident list for the operational UI."""

    status: str
    total: int
    incidents: list[dict[str, Any]]


class IncidentUpdateRequest(BaseModel):
    """State transition request for an incident."""

    status: str = Field(min_length=2)
    actor: str = Field(default="operator")
    owner: str | None = None
    resolution_note: str | None = None


class IncidentActionRequest(BaseModel):
    """Request to execute or preview a runbook-linked action."""

    action_name: str = Field(min_length=2)
    actor: str = Field(default="operator")
    dry_run: bool = Field(default=True)
