"""Audit models for Nexus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AuditEntry:
    """Structured audit event emitted by Nexus."""

    audit_id: str
    flow: str
    action: str
    actor: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
