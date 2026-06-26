"""
app/agents/orchestration_agent.py
-----------------------------------
Orquestador central — recibe consultas, clasifica y delega.

Flujo:
  1. IntentionAgent clasifica y extrae entidades
  2. Si faltan datos → devuelve pregunta de seguimiento
  3. Routing → SSHAgent | JiraAgent | WebAgent | GenerationAgent
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from pydantic import BaseModel

from .analyst_agent import AnalystAgent
from .base_agent import AgentResult
from .coder_agent import CoderAgent
from .generation_agent import GenerationAgent
from .intention_agent import Intencion, IntentionAgent
from .jira_agent import JiraAgent
from .llm_router import LLMRouter, get_router
from .researcher_agent import ResearcherAgent
from .ssh_agent import SSHAgent
from .web_agent import WebAgent

# Modos de agente seleccionables por el usuario desde la UI
_AGENT_OVERRIDE_MAP = {
    "analyst":    "analyst",
    "coder":      "coder",
    "researcher": "researcher",
    "general":    None,   # Sin override — routing automático
}


class OrchestrationResult(BaseModel):
    """
    Resultado completo de una consulta orquestada.

    Contrato canónico — todos los consumidores (worker, API) deben usar
    este modelo directamente. No usar as_legacy_tuple() en código nuevo.
    """
    respuesta: str
    thinking: str = ""
    intencion: str = Intencion.GENERAL
    confianza: float = 0.0
    agente_usado: str = ""
    datos: dict[str, Any] = {}
    exito: bool = True

    def audit_dict(self) -> dict[str, Any]:
        """Devuelve el dict de auditoría para guardar en MongoDB."""
        return {
            "intention":  self.intencion,
            "confidence": self.confianza,
            "agent":      self.agente_usado,
            "success":    self.exito,
            "extra":      self.datos,
        }


class OrchestrationAgent:
    """
    Orquestador principal de NEXUS-UI.

    Crea una única instancia de LLMRouter e inyecta a todos los agentes.
    Reutilizable — no crear una instancia por request.
    """

    def __init__(self) -> None:
        self._router: LLMRouter = get_router()
        self._intention  = IntentionAgent(self._router)

        web_agent = WebAgent(self._router)
        self._agents: dict[Intencion, Any] = {
            Intencion.DIAGNOSTICO_SERVIDOR: SSHAgent(self._router),
            Intencion.CREAR_TICKET_JIRA:    JiraAgent(self._router),
            Intencion.BUSQUEDA_WEB:         web_agent,
            Intencion.GENERAL:              GenerationAgent(self._router),
        }
        # Agentes de modo — seleccionables por el usuario desde la UI
        self._mode_agents: dict[str, Any] = {
            "analyst":    AnalystAgent(self._router),
            "coder":      CoderAgent(self._router),
            "researcher": ResearcherAgent(self._router, web_agent=web_agent),
        }
        logger.info("OrchestrationAgent inicializado")

    async def process_query(
        self,
        user_query: str,
        username: str,
        history: list[dict[str, str]],
        agent_override: str | None = None,
    ) -> OrchestrationResult:
        """
        Interfaz pública del orquestador.
        agent_override: "analyst" | "coder" | "researcher" | None
        Devuelve OrchestrationResult — contrato canónico.
        """
        return await self._orquestar(user_query, username, history, agent_override or None)

    async def process_query_stream(
        self,
        user_query: str,
        username: str,
        history: list[dict[str, str]],
        agent_override: str | None = None,
    ) -> AsyncGenerator[str | dict, None]:
        """
        Versión streaming de process_query().

        Yield:
          - str  : chunk de texto parcial durante la generación
          - dict : {"__done__": True, "result": OrchestrationResult} al finalizar

        Los agentes no-streaming (SSH, Jira, Web) emiten la respuesta completa
        como un único chunk str y luego el __done__. El frontend es transparente.
        """
        try:
            clasificacion = await self._intention.classify(user_query, history)

            logger.info(
                "Orchestrator stream | usuario={} | intencion={} | confianza={:.2f}",
                username, clasificacion.intention, clasificacion.confidence,
            )

            if clasificacion.follow_up_question:
                yield clasificacion.follow_up_question
                yield {
                    "__done__": True,
                    "result": OrchestrationResult(
                        respuesta=clasificacion.follow_up_question,
                        intencion=clasificacion.intention,
                        confianza=clasificacion.confidence,
                        agente_usado="intention_followup",
                    ),
                }
                return

            agente = self._resolver_agente(clasificacion.intention, agent_override)

            if isinstance(agente, GenerationAgent):
                # GenerationAgent y subclases (Analyst, Coder, Researcher): streaming real
                chunks: list[str] = []
                async for chunk in agente.ejecutar_stream(user_query, history):
                    yield chunk
                    chunks.append(chunk)

                from .utils.llm_parser import clean_llm_response
                respuesta = clean_llm_response("".join(chunks))
                yield {
                    "__done__": True,
                    "result": OrchestrationResult(
                        respuesta=respuesta,
                        intencion=clasificacion.intention,
                        confianza=clasificacion.confidence,
                        agente_usado=agente._nombre(),
                        exito=True,
                    ),
                }

            else:
                # SSH, Jira, Web: ejecutar normal, emitir de una vez
                result: AgentResult = await agente.ejecutar(
                    consulta=user_query,
                    entidades=clasificacion.entities,
                    historial=history,
                )
                yield result.respuesta
                yield {
                    "__done__": True,
                    "result": OrchestrationResult(
                        respuesta=result.respuesta,
                        thinking=result.thinking,
                        intencion=clasificacion.intention,
                        confianza=clasificacion.confidence,
                        agente_usado=result.agente,
                        datos=result.datos,
                        exito=result.exito,
                    ),
                }

        except Exception as e:
            logger.exception("Orchestrator stream error | usuario={} | {}", username, e)
            msg = "Error interno del orquestador."
            yield msg
            yield {
                "__done__": True,
                "result": OrchestrationResult(
                    respuesta=msg, exito=False, agente_usado="orchestrator_error"
                ),
            }

    def _resolver_agente(self, intencion: Intencion, agent_override: str | None) -> Any:
        """
        Selecciona el agente a usar.
        Si hay override de modo (analyst/coder/researcher) Y la intención es general,
        usa el agente de modo. Para intenciones especializadas (SSH, Jira, Web)
        el override se ignora — siempre gana el agente técnico.
        """
        if agent_override and intencion == Intencion.GENERAL:
            mode_agent = self._mode_agents.get(agent_override)
            if mode_agent:
                logger.debug("Orchestrator: usando agente de modo | override={}", agent_override)
                return mode_agent
        return self._agents.get(intencion, self._agents[Intencion.GENERAL])

    async def _orquestar(
        self,
        consulta: str,
        username: str,
        historial: list[dict[str, str]],
        agent_override: str | None = None,
    ) -> OrchestrationResult:
        try:
            # 1. Clasificar intención (con historial para resolver ambigüedades en contexto)
            clasificacion = await self._intention.classify(consulta, historial)

            logger.info(
                "Orchestrator | usuario={} | intencion={} | confianza={:.2f} | override={}",
                username,
                clasificacion.intention,
                clasificacion.confidence,
                agent_override or "none",
            )

            # 2. Preguntar si faltan datos obligatorios
            if clasificacion.follow_up_question:
                return OrchestrationResult(
                    respuesta=clasificacion.follow_up_question,
                    intencion=clasificacion.intention,
                    confianza=clasificacion.confidence,
                    agente_usado="intention_followup",
                )

            # 3. Seleccionar agente (respetando override de modo) y ejecutar
            agente = self._resolver_agente(clasificacion.intention, agent_override)

            result: AgentResult = await agente.ejecutar(
                consulta=consulta,
                entidades=clasificacion.entities,
                historial=historial,
            )

            return OrchestrationResult(
                respuesta=result.respuesta,
                thinking=result.thinking,
                intencion=clasificacion.intention,
                confianza=clasificacion.confidence,
                agente_usado=result.agente,
                datos=result.datos,
                exito=result.exito,
            )

        except Exception:
            logger.exception(
                "OrchestrationAgent error no controlado | usuario={}",
                username,
            )
            return OrchestrationResult(
                respuesta=(
                    "Se produjo un error interno procesando tu consulta. "
                    "Por favor inténtalo de nuevo."
                ),
                exito=False,
                agente_usado="orchestrator",
            )
