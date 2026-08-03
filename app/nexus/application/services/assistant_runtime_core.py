"""Shared assistant execution core for web and desktop surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desktop.runtime.skill_router import DesktopSkillRouter, SkillResolution
from nexus.api.schemas.chat import ChatRequest, ChatResponse
from nexus.orchestration.coordinator import NexusCoordinator


@dataclass(slots=True)
class AssistantExecutionRequest:
    """Surface-agnostic execution request."""

    message: str
    user_id: str = "anonymous"
    mode: str = "general"
    context_id: str | None = None
    source_surface: str = "web"
    resolution: dict[str, Any] | None = None


@dataclass(slots=True)
class AssistantExecutionResponse:
    """Surface-agnostic execution response."""

    status: str
    response: str
    agent: str
    flow: str
    audit_id: str
    resolution: dict[str, Any]
    source_surface: str
    run_id: str | None = None

    @classmethod
    def from_chat_response(
        cls,
        response: ChatResponse | dict[str, Any],
        *,
        resolution: dict[str, Any],
        source_surface: str,
    ) -> "AssistantExecutionResponse":
        if isinstance(response, dict):
            return cls(
                status=response["status"],
                response=response["response"],
                agent=response["agent"],
                flow=response["flow"],
                audit_id=response["audit_id"],
                resolution=resolution,
                source_surface=source_surface,
                run_id=response.get("run_id"),
            )
        return cls(
            status=response.status,
            response=response.response,
            agent=response.agent,
            flow=response.flow,
            audit_id=response.audit_id,
            resolution=resolution,
            source_surface=source_surface,
            run_id=getattr(response, "run_id", None),
        )


class AssistantRuntimeCore:
    """Executes assistant requests without coupling callers to FastAPI routes."""

    def __init__(
        self,
        coordinator: NexusCoordinator,
        *,
        skill_router: DesktopSkillRouter | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._skill_router = skill_router or DesktopSkillRouter()
        self._llm_router = llm_router

    async def execute(self, request: AssistantExecutionRequest) -> AssistantExecutionResponse:
        if request.resolution:
            resolution = request.resolution
        elif self._llm_router is not None:
            resolution = (await self._skill_router.resolve_llm(request.message, self._llm_router)).to_dict()
        else:
            resolution = self._skill_router.resolve(request.message).to_dict()
        chat_request = ChatRequest(
            message=request.message,
            user_id=request.user_id,
            mode=request.mode,
            context_id=request.context_id,
        )
        try:
            response = await self._coordinator.handle_chat(
                chat_request,
                resolution_override=resolution,
            )
        except TypeError as exc:
            if "resolution_override" not in str(exc):
                raise
            response = await self._coordinator.handle_chat(chat_request)
        return AssistantExecutionResponse.from_chat_response(
            response,
            resolution=resolution,
            source_surface=request.source_surface,
        )
