"""Chat routes for Nexus v1."""

from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Depends

from metrics import observe_chat_execution
from nexus.api.dependencies.auth import get_assistant_core
from nexus.application.services.assistant_runtime_core import AssistantExecutionRequest, AssistantRuntimeCore
from nexus.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_v1(
    payload: ChatRequest,
    assistant_core: AssistantRuntimeCore = Depends(get_assistant_core),
) -> ChatResponse:
    """Minimal chat surface for Nexus v1."""
    started_at = perf_counter()
    result = await assistant_core.execute(
        AssistantExecutionRequest(
            message=payload.message,
            user_id=payload.user_id,
            mode=payload.mode,
            context_id=payload.context_id,
            source_surface="web",
        )
    )
    observe_chat_execution(
        surface="web",
        mode=payload.mode,
        status=result.status,
        agent=result.agent,
        latency_seconds=perf_counter() - started_at,
    )
    return ChatResponse(
        status=result.status,
        response=result.response,
        agent=result.agent,
        flow=result.flow,
        audit_id=result.audit_id,
        run_id=result.run_id,
        redact_next_reply=result.redact_next_reply,
    )
