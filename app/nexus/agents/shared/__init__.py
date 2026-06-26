"""Shared contracts and primitives for Nexus agents."""

from nexus.agents.shared.base import BaseServerAgent
from nexus.agents.shared.context import AgentExecutionContext
from nexus.agents.shared.registry import AgentRegistry, get_default_agent_registry
from nexus.agents.shared.result import (
    AgentCapability,
    AgentManifest,
    AgentRequest,
    AgentRun,
    PlanStep,
    SkillCall,
)

__all__ = [
    "AgentCapability",
    "AgentExecutionContext",
    "AgentManifest",
    "AgentRegistry",
    "AgentRequest",
    "AgentRun",
    "BaseServerAgent",
    "PlanStep",
    "SkillCall",
    "get_default_agent_registry",
]
