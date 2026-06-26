"""Incident entity for response flows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Incident:
    """Normalized incident tracked by Nexus."""

    incident_id: str
    title: str
    severity: str
    source: str
    next_action: str
    status: str = "open"
    runbook: dict | None = None
    ticket: dict | None = None
    owner: str | None = None
    resolution_note: str | None = None
