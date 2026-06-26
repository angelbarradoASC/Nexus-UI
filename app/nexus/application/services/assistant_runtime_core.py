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
            )
        return cls(
            status=response.status,
            response=response.response,
            agent=response.agent,
            flow=response.flow,
            audit_id=response.audit_id,
            resolution=resolution,
            source_surface=source_surface,
        )


class AssistantRuntimeCore:
    """Executes assistant requests without coupling callers to FastAPI routes."""

    def __init__(
        self,
        coordinator: NexusCoordinator,
        *,
        skill_router: DesktopSkillRouter | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._skill_router = skill_router or DesktopSkillRouter()

    async def execute(self, request: AssistantExecutionRequest) -> AssistantExecutionResponse:
        resolution = request.resolution or self._skill_router.resolve(request.message).to_dict()
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
