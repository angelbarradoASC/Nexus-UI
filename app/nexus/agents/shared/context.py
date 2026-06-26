"""Execution context shared by server-resident Nexus agents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentExecutionContext(BaseModel):
    """Runtime context passed from surfaces into the agent layer."""

    request_id: str
    user_id: str = "anonymous"
    source_surface: str = "desktop"
    correlation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
