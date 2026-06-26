"""Shell agent for the Nexus agentic layer."""

from nexus.agents.shared import (
    AgentExecutionContext,
    AgentRequest,
    BaseServerAgent,
    PlanStep,
    SkillCall,
)
from nexus.agents.shell.manifest import SHELL_MANIFEST


class ShellAgent(BaseServerAgent):
    """Server-side agent for remote execution and evidence collection."""

    manifest = SHELL_MANIFEST

    def build_plan(
        self,
        request: AgentRequest,
        context: AgentExecutionContext,
    ) -> list[PlanStep]:
        return [
            PlanStep(
                step_id="resolve-target",
                title="Resolver objetivo",
                description="Determinar host, credencial y alcance de la accion remota.",
            ),
            PlanStep(
                step_id="collect-evidence",
                title="Recoger evidencia",
                description="Obtener informacion minima antes de ejecutar cambios.",
            ),
            PlanStep(
                step_id="execute-approved-action",
                title="Ejecutar accion aprobada",
                description="Aplicar cambio o comando solo tras validacion explicita.",
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
                skill_id="ssh.run_command",
                connector_id="ssh",
                reason="Verificar estado inicial del objetivo remoto.",
            ),
            SkillCall(
                skill_id="ssh.collect_logs",
                connector_id="ssh",
                reason="Guardar evidencia antes de proponer o ejecutar cambios.",
                risk="medium",
            ),
        ]
