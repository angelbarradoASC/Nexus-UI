"""
app/agents/analyst_agent.py
----------------------------
Agente analista — especializado en análisis de datos, métricas y patrones.
Subclase de GenerationAgent con sistema prompt orientado a análisis estructurado.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from nexus.prompts import resolve_prompt_sync

from .base_agent import AgentResult
from .generation_agent import GenerationAgent

_SYSTEM_PROMPT = (
    "Eres JAINA en modo Analista de Datos. Tu especialidad es analizar información,"
    " identificar patrones, interpretar métricas y extraer conclusiones accionables.\n\n"
    "Directrices:\n"
    "- Estructura siempre tu respuesta: contexto → análisis → conclusión → recomendación.\n"
    "- Usa tablas Markdown cuando presentes datos comparativos.\n"
    "- Incluye porcentajes, tendencias y variaciones cuando sean relevantes.\n"
    "- Si el usuario pide SQL, Python (pandas/numpy) o consultas de datos, proporciona código ejecutable.\n"
    "- Sé preciso con los números — nunca inventes cifras que no tienes.\n"
    "- Responde en el idioma del usuario."
)


class AnalystAgent(GenerationAgent):
    """
    Agente de análisis de datos.
    Mismo motor que GenerationAgent — sistema prompt especializado en análisis.
    """

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        result = await self._ejecutar_con_prompt(consulta, historial, resolve_prompt_sync("agent.analyst"))
        return result

    async def ejecutar_stream(
        self,
        consulta: str,
        historial: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        async for chunk in self._stream_con_prompt(consulta, historial, resolve_prompt_sync("agent.analyst")):
            yield chunk

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
            temperature=0.4,   # Más determinista para análisis
            max_tokens=2000,
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
            temperature=0.4,
            max_tokens=2000,
        ):
            yield chunk
