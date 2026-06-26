"""
app/agents/generation_agent.py
--------------------------------
Agente de respuesta general — usa LLMRouter L0→L3.

Nivel preferido : L2 (balance calidad/coste)
Nivel velocidad : L3 (premium)
Nivel mínimo    : L0 (siempre disponible)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from nexus.prompts import resolve_prompt_sync

from .base_agent import AgentResult, BaseAgent
from .utils.llm_parser import clean_llm_response

_SYSTEM_PROMPT = (
    "Eres JAINA, un asistente de IA útil y conciso. "
    "Responde siempre en el idioma del usuario. "
    "Si no conoces algo con certeza, dilo claramente."
)


class GenerationAgent(BaseAgent):
    """
    Agente de respuesta general.
    Delega en LLMRouter — no tiene lógica de modelo propio.
    """

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        self.logger.debug("GenerationAgent ejecutando | consulta_len={}", len(consulta))

        messages: list[dict[str, str]] = [
            {"role": "system", "content": resolve_prompt_sync("agent.general")},
        ]
        messages.extend(self._construir_historial_ventana(historial))
        messages.append({"role": "user", "content": consulta})

        result = await self.router.call(
            messages,
            min_level=0,
            preferred_level=2,
            speed_level=3,
            temperature=0.7,
            max_tokens=1500,
        )

        if result.error:
            self.logger.error(
                "GenerationAgent error del router | error={}",
                result.error,
            )
            return self._resultado_fallo(
                "Lo siento, no puedo conectar con el servicio de IA. "
                "Verifica que LMStudio esté en ejecución o que las claves cloud estén configuradas.",
                result.error,
            )

        contenido = clean_llm_response(result.content)

        self.logger.info(
            "GenerationAgent OK | nivel=L{} | modelo={} | latencia={}ms",
            result.level_used,
            result.model_used,
            result.latency_ms,
        )

        return AgentResult(
            respuesta=contenido,
            exito=True,
            agente=self._nombre(),
            datos={
                "level_used": result.level_used,
                "model_used": result.model_used,
                "latency_ms": result.latency_ms,
                "tokens_in": result.tokens_input,
                "tokens_out": result.tokens_output,
            },
        )

    async def ejecutar_stream(
        self,
        consulta: str,
        historial: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        """
        Versión streaming de ejecutar(). Yield chunks de texto conforme llegan del LLM.
        El caller acumula los chunks para obtener la respuesta completa.
        """
        self.logger.debug("GenerationAgent stream | consulta_len={}", len(consulta))

        messages: list[dict[str, str]] = [
            {"role": "system", "content": resolve_prompt_sync("agent.general")},
        ]
        messages.extend(self._construir_historial_ventana(historial))
        messages.append({"role": "user", "content": consulta})

        async for chunk in self.router.call_stream(
            messages,
            min_level=0,
            preferred_level=2,
            speed_level=3,
            temperature=0.7,
            max_tokens=1500,
        ):
            yield chunk

    async def generate_response(
        self,
        prompt: str,
        username: str,
        history: list[dict[str, str]],
    ) -> str:
        """
        Interfaz de compatibilidad usada por SSHAgent, JiraAgent y WebAgent.
        Llama a ejecutar() internamente.
        """
        result = await self.ejecutar(prompt, {}, history)
        return result.respuesta
