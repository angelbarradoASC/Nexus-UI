"""
app/agents/researcher_agent.py
--------------------------------
Agente investigador — combina búsqueda web con síntesis profunda.
Para consultas de investigación activa usa WebAgent primero, luego sintetiza.
Para conocimiento general actúa como GenerationAgent con prompt de investigador.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from nexus.prompts import resolve_prompt_sync

from .base_agent import AgentResult
from .generation_agent import GenerationAgent

_SYSTEM_PROMPT = (
    "Eres JAINA en modo Investigador. Tu especialidad es investigar en profundidad,"
    " contrastar fuentes y elaborar informes comprensivos y bien estructurados.\n\n"
    "Directrices:\n"
    "- Estructura tu respuesta como un informe: resumen ejecutivo → desarrollo → conclusiones.\n"
    "- Cita explícitamente cuando basas algo en datos concretos vs. conocimiento general.\n"
    "- Indica el nivel de certeza cuando no puedas verificar algo.\n"
    "- Usa secciones con cabeceras Markdown para investigaciones largas.\n"
    "- Si la pregunta requiere información actual (noticias, precios, estado de servicios),"
    "  indícalo claramente — activa la herramienta web si está disponible.\n"
    "- Profundiza más que el asistente general — no te limites a la respuesta superficial.\n"
    "- Responde en el idioma del usuario."
)


class ResearcherAgent(GenerationAgent):
    """
    Agente investigador.
    Usa síntesis profunda para conocimiento general.
    Delega en WebAgent cuando la consulta requiere información en tiempo real.
    """

    def __init__(self, router: Any, web_agent: Any | None = None) -> None:
        super().__init__(router)
        self._web_agent = web_agent  # Inyectado por OrchestrationAgent

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        # Si hay WebAgent disponible y la consulta parece requerir datos actuales,
        # obtener contexto web primero y luego sintetizar
        web_context = ""
        if self._web_agent and self._necesita_web(consulta):
            try:
                web_result = await self._web_agent.ejecutar(consulta, entidades, historial)
                if web_result.exito:
                    web_context = f"\n\nContexto obtenido de búsqueda web:\n{web_result.respuesta}"
                    logger.debug("ResearcherAgent: contexto web obtenido")
            except Exception as e:
                logger.warning("ResearcherAgent: búsqueda web fallida | {}", e)

        consulta_enriquecida = consulta + web_context
        return await self._ejecutar_con_prompt(consulta_enriquecida, historial, resolve_prompt_sync("agent.researcher"))

    async def ejecutar_stream(
        self,
        consulta: str,
        historial: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        # Para streaming, sintetizar directamente (web previa añadiría latencia visible)
        async for chunk in self._stream_con_prompt(consulta, historial, resolve_prompt_sync("agent.researcher")):
            yield chunk

    @staticmethod
    def _necesita_web(consulta: str) -> bool:
        """Heurística rápida: ¿la consulta probablemente necesita datos actuales?"""
        keywords = (
            "hoy", "ahora", "actual", "último", "reciente", "precio", "cotización",
            "noticias", "noticia", "estado", "versión", "changelog", "release",
            "today", "current", "latest", "news", "price", "status",
        )
        consulta_lower = consulta.lower()
        return any(kw in consulta_lower for kw in keywords)

    async def _ejecutar_con_prompt(
        self,
        consulta: str,
        historial: list[dict[str, str]],
        system_prompt: str,
    ) -> AgentResult:
        from .utils.llm_parser import clean_llm_response

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._construir_historial_ventana(historial))
        messages.append({"role": "user", "content": consulta})

        result = await self.router.call(
            messages,
            min_level=0,
            preferred_level=2,
            speed_level=3,
            temperature=0.5,
            max_tokens=2500,
        )

        if result.error:
            return self._resultado_fallo(
                "No puedo conectar con el servicio de IA.", result.error
            )

        return AgentResult(
            respuesta=clean_llm_response(result.content),
            exito=True,
            agente=self._nombre(),
            datos={"level_used": result.level_used, "model_used": result.model_used},
        )

    async def _stream_con_prompt(
        self,
        consulta: str,
        historial: list[dict[str, str]],
        system_prompt: str,
    ) -> AsyncGenerator[str, None]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._construir_historial_ventana(historial))
        messages.append({"role": "user", "content": consulta})

        async for chunk in self.router.call_stream(
            messages,
            min_level=0,
            preferred_level=2,
            speed_level=3,
            temperature=0.5,
            max_tokens=2500,
        ):
            yield chunk
