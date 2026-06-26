"""Operator agent for the Nexus agentic layer."""

from nexus.agents.operator.manifest import OPERATOR_MANIFEST
from nexus.agents.operator.skills_map import OPERATOR_SKILL_MAP
from nexus.agents.shared import (
    AgentExecutionContext,
    AgentRequest,
    BaseServerAgent,
    PlanStep,
    SkillCall,
)


class OperatorAgent(BaseServerAgent):
    """Server-side agent for observability and incident workflows."""

    manifest = OPERATOR_MANIFEST

    def build_plan(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[PlanStep]:
        return [
            PlanStep(
                step_id="collect-observability",
                title="Recoger observabilidad",
                description="Consultar metricas, alertas y dashboards relevantes.",
            ),
            PlanStep(
                step_id="correlate-signals",
                title="Correlacionar senales",
                description="Cruzar sintomas, impacto y tecnologia afectada.",
            ),
            PlanStep(
                step_id="prepare-response",
                title="Preparar respuesta",
                description="Proponer siguiente accion, runbook o escalado.",
                requires_approval=True,
            ),
        ]

    def build_skill_calls(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[SkillCall]:
        return [
            SkillCall(
                skill_id="observability.check_alerts",
                connector_id="alertmanager",
                reason="Leer el estado actual de las alertas antes de actuar.",
            ),
            SkillCall(
                skill_id="observability.query_prometheus",
                connector_id="prometheus",
                reason="Verificar metricas base asociadas al incidente o consulta.",
            ),
        ]
