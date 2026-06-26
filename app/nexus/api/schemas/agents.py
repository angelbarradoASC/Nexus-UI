"""Schemas for the server-resident agent catalog."""

from __future__ import annotations

from pydantic import BaseModel, Field

from nexus.agents.shared.result import AgentManifest, AgentRequest, AgentRun


class AgentCatalogContracts(BaseModel):
    """Canonical model names shared by desktop and web consumers."""

    request_model: str
    run_model: str
    manifest_model: str
    plan_step_model: str
    skill_call_model: str


class AgentCatalogResponse(BaseModel):
    """Surface-agnostic description of the Nexus agent layer."""

    status: str = "success"
    delivery_model: str = "server_resident"
    surfaces: list[str] = Field(default_factory=lambda: ["desktop", "web"])
    contracts: AgentCatalogContracts
    agents: list[AgentManifest]


class AgentRunCreateRequest(AgentRequest):
    """Body used to bootstrap a shared agent run from any surface."""


class AgentRunListResponse(BaseModel):
    """List payload for stored server-side runs."""

    status: str = "success"
    total: int
    runs: list[AgentRun]
