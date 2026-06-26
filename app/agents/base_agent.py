"""
app/agents/base_agent.py
-------------------------
Contrato base para todos los agentes de NEXUS-UI.

Estándar 05_IA_AGENTES.md:
  - BaseAgent: clase abstracta con router inyectado
  - AgentResult: resultado estándar Pydantic
  - Todos los agentes implementan ejecutar()

Uso:
    class MiAgente(BaseAgent):
        async def ejecutar(self, consulta, entidades, historial) -> AgentResult:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """
    Resultado estándar devuelto por todos los agentes.

    - respuesta: texto en lenguaje natural para el usuario
    - exito: False si hubo un error manejado
    - agente: nombre de la clase del agente que lo generó
    - datos: dict con información extra (audit, metrics, etc.)
    - error: mensaje técnico si exito=False
    - thinking: cadena de razonamiento interno (opcional, para debug)
    """

    respuesta: str
    exito: bool = True
    agente: str = ""
    datos: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    thinking: str = ""

    @classmethod
    def fallo(cls, agente: str, mensaje: str, error: str = "") -> "AgentResult":
        """Factory para resultados de error — evita repetir boilerplate."""
        return cls(
            respuesta=mensaje,
            exito=False,
            agente=agente,
            error=error or mensaje,
        )


class BaseAgent(ABC):
    """
    Clase base abstracta para todos los agentes de NEXUS-UI.

    Responsabilidades de los subclases:
      1. Implementar ejecutar()
      2. Usar self.logger para todos los logs
      3. Devolver siempre AgentResult (nunca lanzar excepciones al orquestador)
      4. NO acceder a os.environ directamente — usar config o self.router

    No instanciar directamente: usar las subclases.
    """

    def __init__(self, router: Any) -> None:
        """
        Args:
            router: instancia de LLMRouter inyectada por OrchestrationAgent.
                    Tipo Any para evitar import circular; en runtime es LLMRouter.
        """
        self.router = router
        self.logger = logger.bind(agent=self._nombre())

    @abstractmethod
    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        """
        Ejecuta la lógica del agente.

        Args:
            consulta:  Texto completo de la consulta del usuario.
            entidades: Dict con entidades extraídas por IntentionAgent.
            historial: Lista de mensajes previos (formato OpenAI).

        Returns:
            AgentResult siempre. Nunca lanza excepciones no controladas.
        """
        ...

    def _nombre(self) -> str:
        """Nombre canónico del agente (nombre de clase)."""
        return self.__class__.__name__

    def _resultado_fallo(self, mensaje: str, error: str = "") -> AgentResult:
        """Shortcut para devolver un AgentResult de fallo."""
        return AgentResult.fallo(self._nombre(), mensaje, error)

    def _construir_historial_ventana(
        self,
        historial: list[dict[str, str]],
        max_turnos: int = 6,
    ) -> list[dict[str, str]]:
        """
        Devuelve los últimos N turnos del historial para el prompt.
        Evita inyectar contexto infinito que sature el LLM.
        """
        return historial[-max_turnos:] if historial else []
