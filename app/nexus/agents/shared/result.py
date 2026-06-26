"""Shared contracts for server-resident Nexus agents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentCapability(BaseModel):
    """One stable capability exposed by an agent role."""

    capability_id: str
    name: str
    description: str


class AgentManifest(BaseModel):
    """Static description of an agent role available to all surfaces."""

    agent_id: str
    name: str
    role: str
    description: str
    server_resident: bool = True
    supported_surfaces: list[str] = Field(default_factory=lambda: ["desktop", "web"])
    accepted_modes: list[str] = Field(default_factory=list)
    capabilities: list[AgentCapability] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    connector_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class AgentRequest(BaseModel):
    """Surface-agnostic request sent to the agentic layer."""

    message: str = Field(min_length=1)
    user_id: str = Field(default="anonymous")
    source_surface: str = Field(default="desktop")
    mode: str = Field(default="general")
    target_agent_id: str | None = None
    context_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    """One visible step inside an agent plan."""

    step_id: str
    title: str
    description: str = ""
    status: str = "pending"
    requires_approval: bool = False


class SkillCall(BaseModel):
    """One planned skill invocation produced by an agent."""

    skill_id: str
    connector_id: str
    reason: str
    risk: str = "low"


class AgentRun(BaseModel):
    """Canonical run payload shared across desktop and web."""

    run_id: str
    agent_id: str
    source_surface: str
    status: str = "planned"
    summary: str
    plan_steps: list[PlanStep] = Field(default_factory=list)
    skill_calls: list[SkillCall] = Field(default_factory=list)
    explanation: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
