"""Dispatches tasks into the proper orchestration flow."""

from __future__ import annotations

from nexus.api.schemas.chat import ChatRequest, ChatResponse
from nexus.api.schemas.incidents import IncidentIngestRequest, IncidentResponse
from nexus.orchestration.coordinator import NexusCoordinator


class TaskDispatcher:
    """Thin application service over the Nexus coordinator."""

    def __init__(self, coordinator: NexusCoordinator) -> None:
        self._coordinator = coordinator

    async def dispatch_chat(self, payload: ChatRequest) -> ChatResponse:
        return await self._coordinator.handle_chat(payload)

    async def dispatch_incident(self, payload: IncidentIngestRequest) -> IncidentResponse:
        return await self._coordinator.handle_incident(payload)
