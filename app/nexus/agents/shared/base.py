"""Base class for Nexus server-resident agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import uuid4

from nexus.agents.shared.context import AgentExecutionContext
from nexus.agents.shared.result import AgentManifest, AgentRequest, AgentRun, PlanStep, SkillCall


class BaseServerAgent(ABC):
    """Shared bootstrap behavior for desktop/web agent roles."""

    manifest: AgentManifest

    def describe(self) -> AgentManifest:
        return self.manifest

    @abstractmethod
    def build_plan(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[PlanStep]:
        """Build the initial visible plan for a request."""

    def build_skill_calls(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[SkillCall]:
        """Return the planned skill calls for the request."""
        return []

    def bootstrap_run(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> AgentRun:
        """Create a first-class run payload consumable by desktop and web."""
        return AgentRun(
            run_id=f"run-{uuid4().hex[:12]}",
            agent_id=self.manifest.agent_id,
            source_surface=request.source_surface,
            summary=self.manifest.description,
            plan_steps=self.build_plan(request, context),
            skill_calls=self.build_skill_calls(request, context),
            explanation=(
                f"{self.manifest.name} se ejecuta en servidor y comparte el mismo "
                "contrato operativo para desktop y web."
            ),
            metadata={
                "mode": request.mode,
                "context_id": request.context_id,
                "target_agent_id": request.target_agent_id,
            },
        )
