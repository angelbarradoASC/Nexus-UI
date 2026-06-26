"""Supervisor agent for the Nexus agentic layer."""

from nexus.agents.shared import AgentExecutionContext, AgentRequest, BaseServerAgent, PlanStep
from nexus.agents.supervisor.manifest import SUPERVISOR_MANIFEST


class SupervisorAgent(BaseServerAgent):
    """Creates the initial plan and picks the next agent role."""

    manifest = SUPERVISOR_MANIFEST

    def build_plan(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[PlanStep]:
        return [
            PlanStep(
                step_id="classify-intent",
                title="Clasificar intencion",
                description="Resolver el objetivo y el rol mas adecuado para la tarea.",
            ),
            PlanStep(
                step_id="select-agent",
                title="Seleccionar agente",
                description="Delegar en operator, shell o sales segun el plan.",
            ),
            PlanStep(
                step_id="explain-rationale",
                title="Explicar razonamiento",
                description="Dejar trazabilidad entendible para desktop y web.",
            ),
        ]
