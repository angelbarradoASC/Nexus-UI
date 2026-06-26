"""Sales agent for the Nexus agentic layer."""

from nexus.agents.sales.manifest import SALES_MANIFEST
from nexus.agents.shared import AgentExecutionContext, AgentRequest, BaseServerAgent, PlanStep


class SalesAgent(BaseServerAgent):
    """Server-side agent for prospecting and CRM workflows."""

    manifest = SALES_MANIFEST

    def build_plan(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[PlanStep]:
        return [
            PlanStep(
                step_id="brief-guardian",
                title="Brief Guardian",
                description="Blindar la intencion comercial y los guardrails base.",
            ),
            PlanStep(
                step_id="brief-refiner",
                title="Brief Refiner",
                description="Refinar el briefing sin tocar geografia, marca ni volumen.",
            ),
            PlanStep(
                step_id="source-strategist",
                title="Source Strategist",
                description="Resolver el orden de discovery y el fallback comercial.",
            ),
            PlanStep(
                step_id="query-architect",
                title="Query Architect",
                description="Construir queries de baja friccion y buen contacto.",
            ),
            PlanStep(
                step_id="search-executor",
                title="Search Executor",
                description="Ejecutar Brave y Google Places con trazabilidad.",
            ),
            PlanStep(
                step_id="candidate-qualifier",
                title="Candidate Qualifier",
                description="Validar, deduplicar y puntuar candidatos.",
            ),
            PlanStep(
                step_id="crm-packager",
                title="CRM Packager",
                description="Preparar el handoff final a CRM y outreach.",
                requires_approval=True,
            ),
        ]
