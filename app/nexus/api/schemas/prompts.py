"""Schemas for editable Nexus prompts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PromptUpdateRequest(BaseModel):
    """Payload for updating a prompt."""

    current_text: str = Field(min_length=20)


class PromptRecordResponse(BaseModel):
    """Single prompt record returned by the API."""

    key: str
    title: str
    group: str
    description: str
    default_text: str
    current_text: str
    is_overridden: bool


class PromptListResponse(BaseModel):
    """List response for prompt catalogue UI."""

    status: str
    total: int
    prompts: list[dict[str, Any]]


class PromptEnvelopeResponse(BaseModel):
    """Single prompt envelope response."""

    status: str
    prompt: PromptRecordResponse
