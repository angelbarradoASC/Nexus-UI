"""Chat request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload for the Nexus v1 chat endpoint."""

    message: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    mode: str = Field(default="general")
    context_id: str | None = None


class ChatResponse(BaseModel):
    """Response returned by the Nexus v1 chat endpoint."""

    status: str
    response: str
    agent: str
    flow: str
    audit_id: str
    run_id: str | None = None
