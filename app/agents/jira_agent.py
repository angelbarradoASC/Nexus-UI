"""
app/agents/jira_agent.py
-------------------------
Agente JIRA — crea, consulta tickets en Jira Cloud.
Usa JiraClient para la API; GenerationAgent si falta información.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from .base_agent import AgentResult, BaseAgent
from .generation_agent import GenerationAgent
from .tools.jira_client import JiraClient


class JiraAgent(BaseAgent):
    """
    Procesa intenciones de tipo 'crear_ticket_jira'.
    Devuelve siempre AgentResult — nunca lanza al orquestador.
    """

    def __init__(self, router: Any) -> None:
        super().__init__(router)
        self._jira = JiraClient()
        self._llm = GenerationAgent(router)

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        if not self._jira.enabled:
            return AgentResult(
                respuesta=(
                    "JIRA no está configurado. "
                    "Establece USE_JIRA=true y las variables JIRA_* en .env."
                ),
                exito=False,
                agente=self._nombre(),
                error="jira_disabled",
            )

        accion = (entidades.get("accion") or "crear").lower()

        try:
            if accion == "consultar":
                return await self._consultar(consulta, entidades, historial)
            else:
                return await self._crear(consulta, entidades, historial)

        except Exception as e:
            logger.exception("JiraAgent error inesperado | accion={}", accion)
            return self._resultado_fallo(
                f"Error al interactuar con JIRA: {e}",
                str(e),
            )

    # ── Acciones ─────────────────────────────────────────────────────────────

    async def _crear(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        summary = entidades.get("resumen") or entidades.get("problema")
        descripcion = entidades.get("descripcion") or consulta

        if not summary:
            prompt = (
                f"El usuario quiere crear un ticket en Jira pero no ha especificado "
                f"el título. Su mensaje: '{consulta}'. "
                f"Pídele amablemente el título y la descripción."
            )
            respuesta = await self._llm.generate_response(
                prompt, "system", self._construir_historial_ventana(historial)
            )
            return AgentResult(
                respuesta=respuesta,
                exito=True,
                agente=self._nombre(),
                datos={"pending_action": "crear_ticket"},
            )

        issue_type = entidades.get("tipo_ticket") or "Task"
        data = await self._jira.create_issue(
            summary=summary,
            description=descripcion,
            issue_type=issue_type,
        )

        respuesta = (
            f"Ticket creado correctamente:\n\n"
            f"- **Clave:** {data['key']}\n"
            f"- **Tipo:** {issue_type}\n"
            f"- **Resumen:** {summary}\n"
            f"- **URL:** {data['url']}"
        )
        logger.info("JiraAgent ticket creado | key={}", data["key"])
        return AgentResult(
            respuesta=respuesta,
            exito=True,
            agente=self._nombre(),
            datos=data,
        )

    async def _consultar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        issue_key = entidades.get("ticket_id")
        if not issue_key:
            prompt = (
                f"El usuario quiere consultar un ticket de Jira pero no indicó la clave "
                f"(ej: NEXUS-42). Su mensaje: '{consulta}'. Pídele la clave."
            )
            respuesta = await self._llm.generate_response(
                prompt, "system", self._construir_historial_ventana(historial)
            )
            return AgentResult(
                respuesta=respuesta,
                exito=True,
                agente=self._nombre(),
            )

        issue = await self._jira.get_issue(issue_key)
        respuesta = (
            f"**{issue['key']}** — {issue['summary']}\n\n"
            f"- **Estado:** {issue['status']}\n"
            f"- **Asignado a:** {issue['assignee']}\n"
            f"- **Prioridad:** {issue['priority']}\n"
            f"- **URL:** {issue['url']}"
        )
        logger.info("JiraAgent consulta OK | key={}", issue_key)
        return AgentResult(
            respuesta=respuesta,
            exito=True,
            agente=self._nombre(),
            datos=issue,
        )
