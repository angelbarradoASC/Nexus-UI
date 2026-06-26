"""Server-side runtime for Nexus agent runs shared by desktop and web."""

from __future__ import annotations

from uuid import uuid4

from nexus.agents import get_default_agent_registry
from nexus.agents.shared import AgentExecutionContext, AgentRegistry, AgentRequest, AgentRun


class AgentRuntimeService:
    """Creates and stores server-resident agent runs behind one shared contract."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or get_default_agent_registry()
        self._runs: dict[str, AgentRun] = {}

    def list_runs(
        self,
        *,
        source_surface: str | None = None,
        agent_id: str | None = None,
    ) -> list[AgentRun]:
        runs = list(self._runs.values())
        if source_surface is not None:
            runs = [run for run in runs if run.source_surface == source_surface]
        if agent_id is not None:
            runs = [run for run in runs if run.agent_id == agent_id]
        return runs

    def get_run(self, run_id: str) -> AgentRun | None:
        return self._runs.get(run_id)

    def create_run(self, request: AgentRequest) -> AgentRun:
        agent = self._resolve_agent(request)
        context = AgentExecutionContext(
            request_id=f"req-{uuid4().hex[:12]}",
            user_id=request.user_id,
            source_surface=request.source_surface,
            metadata={
                "mode": request.mode,
                **request.metadata,
            },
        )
        run = agent.bootstrap_run(request, context)
        run.metadata["resolved_agent_id"] = run.agent_id
        if request.target_agent_id:
            run.metadata["requested_agent_id"] = request.target_agent_id
        else:
            next_agent_id = self._resolve_next_agent_id(request)
            if next_agent_id != run.agent_id:
                run.metadata["next_agent_id"] = next_agent_id
        self._runs[run.run_id] = run
        return run

    def _resolve_agent(self, request: AgentRequest):
        resolved_agent_id = self._resolve_next_agent_id(request)
        return self._registry.get(resolved_agent_id)

    def _resolve_next_agent_id(self, request: AgentRequest) -> str:
        if request.target_agent_id:
            return request.target_agent_id

        mode = request.mode.strip().lower()
        if mode in {"operator", "monitoring", "incident"}:
            return "operator"
        if mode in {"shell", "execution", "investigation"}:
            return "shell"
        if mode in {"sales", "prospecting", "crm", "outreach"}:
            return "sales"
        return "supervisor"
