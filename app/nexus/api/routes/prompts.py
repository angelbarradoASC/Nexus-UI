"""Routes for editing live Nexus prompts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nexus.api.dependencies.auth import get_prompt_manager
from nexus.api.schemas.prompts import PromptEnvelopeResponse, PromptListResponse, PromptUpdateRequest
from nexus.prompts import PromptManager

router = APIRouter()


@router.get("/prompts", response_model=PromptListResponse)
async def list_prompts(
    prompts: PromptManager = Depends(get_prompt_manager),
) -> PromptListResponse:
    """List all editable Nexus prompts."""
    return await prompts.list_prompts()


@router.get("/prompts/{prompt_key}", response_model=PromptEnvelopeResponse)
async def get_prompt(
    prompt_key: str,
    prompts: PromptManager = Depends(get_prompt_manager),
) -> PromptEnvelopeResponse:
    """Return a single prompt with current and default text."""
    try:
        return await prompts.get_prompt(prompt_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_key} not found") from exc


@router.put("/prompts/{prompt_key}", response_model=PromptEnvelopeResponse)
async def update_prompt(
    prompt_key: str,
    payload: PromptUpdateRequest,
    prompts: PromptManager = Depends(get_prompt_manager),
) -> PromptEnvelopeResponse:
    """Update a live Nexus prompt."""
    try:
        return await prompts.update_prompt(prompt_key, payload.current_text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_key} not found") from exc


@router.post("/prompts/{prompt_key}/reset", response_model=PromptEnvelopeResponse)
async def reset_prompt(
    prompt_key: str,
    prompts: PromptManager = Depends(get_prompt_manager),
) -> PromptEnvelopeResponse:
    """Reset a prompt back to its default text."""
    try:
        return await prompts.reset_prompt(prompt_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_key} not found") from exc
