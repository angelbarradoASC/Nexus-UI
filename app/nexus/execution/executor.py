"""Central executor for approved actions."""

from __future__ import annotations

from nexus.domain.entities.tool_action import ToolAction


class ExecutionExecutor:
    """Very small executor façade for v1."""

    async def execute(self, action: ToolAction) -> dict[str, str]:
        return {
            "status": "accepted",
            "action": action.name,
            "target": action.target,
            "risk": action.risk,
        }
