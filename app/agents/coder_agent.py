"""
app/agents/coder_agent.py
--------------------------
Agente de código — especializado en generación, depuración y refactoring.
Subclase de GenerationAgent con sistema prompt orientado a ingeniería de software.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from nexus.prompts import resolve_prompt_sync

from .base_agent import AgentResult
from .generation_agent import GenerationAgent

_SYSTEM_PROMPT = (
    "Eres JAINA en modo Generador de Código. Tu especialidad es escribir, depurar"
    " y refactorizar código de alta calidad.\n\n"
    "Directrices:\n"
    "- Proporciona siempre código completo y ejecutable — no fragmentos incompletos.\n"
    "- Usa bloques de código Markdown con el lenguaje explícito (```python, ```typescript, etc.).\n"
    "- Incluye comentarios solo donde aporten valor real — no sobrecomentes lo obvio.\n"
    "- Si detectas un bug, explica la causa raíz antes de mostrar la corrección.\n"
    "- Para refactoring, muestra el antes y el después con una explicación breve.\n"
    "- Sugiere mejoras de rendimiento, seguridad o legibilidad cuando sean relevantes.\n"
    "- Si necesitas información que no tienes (versión, contexto del proyecto), pregúntala.\n"
    "- Responde en el idioma del usuario."
)


class CoderAgent(GenerationAgent):
    """
    Agente de generación de código.
    Mismo motor que GenerationAgent — sistema prompt especializado en código.
    """

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        return await self._ejecutar_con_prompt(consulta, historial, resolve_prompt_sync("agent.coder"))

    async def ejecutar_stream(
        self,
        consulta: str,
        historial: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        async for chunk in self._stream_con_prompt(consulta, historial, resolve_prompt_sync("agent.coder")):
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
            temperature=0.2,   # Bajo — código preciso y reproducible
            max_tokens=3000,   # Más tokens para bloques de código completos
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
            temperature=0.2,
            max_tokens=3000,
        ):
            yield chunk
