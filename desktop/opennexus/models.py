"""Shared models for Open-Nexus desktop runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class OpenNexusResult:
    """Resolved desktop command plus Nexus response."""

    user_input: str
    resolution: dict[str, Any]
    response: str
    agent: str
    status: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_input": self.user_input,
            "resolution": self.resolution,
            "response": self.response,
            "agent": self.agent,
            "status": self.status,
            "created_at": self.created_at,
        }
