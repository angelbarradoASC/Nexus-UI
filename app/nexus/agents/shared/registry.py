"""Registry for server-resident Nexus agents."""

from __future__ import annotations

from nexus.agents.shared.base import BaseServerAgent
from nexus.agents.shared.result import AgentManifest


class AgentRegistry:
    """Stable catalog of agent roles available to all Nexus surfaces."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseServerAgent] = {}

    def register(self, agent: BaseServerAgent) -> None:
        self._agents[agent.describe().agent_id] = agent

    def get(self, agent_id: str) -> BaseServerAgent:
        return self._agents[agent_id]

    def list_agents(self) -> list[BaseServerAgent]:
        return list(self._agents.values())

    def list_manifests(self, *, surface: str | None = None) -> list[AgentManifest]:
        manifests = [agent.describe() for agent in self.list_agents()]
        if surface is None:
            return manifests
        return [
            manifest
            for manifest in manifests
            if surface in manifest.supported_surfaces
        ]


_default_registry: AgentRegistry | None = None


def get_default_agent_registry() -> AgentRegistry:
    """Return the canonical registry used by desktop and web."""
    global _default_registry

    if _default_registry is None:
        from nexus.agents.operator.agent import OperatorAgent
        from nexus.agents.sales.agent import SalesAgent
        from nexus.agents.shell.agent import ShellAgent
        from nexus.agents.supervisor.agent import SupervisorAgent

        registry = AgentRegistry()
        registry.register(SupervisorAgent())
        registry.register(OperatorAgent())
        registry.register(ShellAgent())
        registry.register(SalesAgent())
        _default_registry = registry

    return _default_registry
