"""
app/agents/execution_context.py
---------------------------------
AgentExecutionContext — el wrapper de ejecución que todos los agentes deben usar
cuando realizan acciones sobre sistemas externos.

Implementa los 4 pilares del sistema agentico de NEXUS:

  1. TRACE      — cada paso registrado: input, thought, action, result, timing
  2. GUARDRAILS — clasificación de riesgo antes de ejecutar (código, no LLM)
  3. REASONING  — cadena estructurada de pasos interpretable por humanos
  4. HUMAN LOOP — pausa automática para acciones que superan el umbral de riesgo

Uso básico:
    ctx = AgentExecutionContext(
        triggered_by="angel",
        agent_name="SSHAgent",
        model_used="openai/gpt-oss-120b",
        model_tier=1,
    )
    step = await ctx.execute_step(
        thought="Necesito ver el uso de disco para detectar el problema",
        action="df -h",
        executor=lambda: ssh.run("df -h"),
    )
    trace = ctx.finalize("Disco al 95% en /var — limpiar logs")

Los agentes que NO usen este contexto siguen funcionando igual (compatibilidad).
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from nexus.policy.guardrails import GuardrailEngine, GuardrailVerdict, RiskClass


# ── Modelos de datos ──────────────────────────────────────────────────────────

@dataclass
class ReasoningStep:
    """Un paso individual en la cadena de razonamiento del agente."""
    step:           int
    thought:        str           # Por qué el agente toma esta acción
    action:         str           # Qué acción/comando ejecuta
    risk_class:     RiskClass
    risk_score:     float
    verdict:        str           # auto_approved | human_required | blocked
    verdict_reason: str
    result:         str | None = None      # Output de la ejecución (truncado)
    observation:    str | None = None      # Interpretación del resultado
    approved_by:    str | None = None      # Quién aprobó (si human_required)
    duration_ms:    int | None = None
    error:          str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step":           self.step,
            "thought":        self.thought,
            "action":         self.action,
            "risk_class":     self.risk_class.value,
            "risk_score":     round(self.risk_score, 3),
            "verdict":        self.verdict,
            "verdict_reason": self.verdict_reason,
            "result":         self.result,
            "observation":    self.observation,
            "approved_by":    self.approved_by,
            "duration_ms":    self.duration_ms,
            "error":          self.error,
        }


@dataclass
class AgentTrace:
    """
    Traza completa e inmutable de una ejecución de agente.
    Se persiste en el audit repository al finalizar.
    """
    trace_id:      str
    audit_id:      str
    agent:         str
    model_used:    str
    model_tier:    int
    triggered_by:  str
    started_at:    str
    completed_at:  str | None
    input_summary: str
    steps:         list[ReasoningStep] = field(default_factory=list)
    conclusion:    str | None = None
    final_status:  str = "completed"   # completed | blocked | failed | pending_approval

    @property
    def has_pending(self) -> bool:
        return any(s.verdict == "human_required" for s in self.steps)

    @property
    def is_blocked(self) -> bool:
        return any(s.verdict == "blocked" for s in self.steps)

    @property
    def highest_risk_class(self) -> RiskClass:
        order = {RiskClass.BLOCKED: 4, RiskClass.DESTRUCTIVE: 3,
                 RiskClass.WRITE: 2, RiskClass.READ: 1}
        if not self.steps:
            return RiskClass.READ
        return max(self.steps, key=lambda s: order.get(s.risk_class, 0)).risk_class

    def to_audit_details(self) -> dict[str, Any]:
        return {
            "trace_id":      self.trace_id,
            "agent":         self.agent,
            "model_used":    self.model_used,
            "model_tier":    self.model_tier,
            "steps_count":   len(self.steps),
            "highest_risk":  self.highest_risk_class.value,
            "has_pending":   self.has_pending,
            "is_blocked":    self.is_blocked,
            "conclusion":    self.conclusion,
            "final_status":  self.final_status,
            "reasoning_chain": [s.to_dict() for s in self.steps],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id":      self.trace_id,
            "audit_id":      self.audit_id,
            "agent":         self.agent,
            "model_used":    self.model_used,
            "model_tier":    self.model_tier,
            "triggered_by":  self.triggered_by,
            "started_at":    self.started_at,
            "completed_at":  self.completed_at,
            "input_summary": self.input_summary,
            "conclusion":    self.conclusion,
            "final_status":  self.final_status,
            "highest_risk":  self.highest_risk_class.value,
            "steps":         [s.to_dict() for s in self.steps],
        }


# ── Contexto de ejecución ─────────────────────────────────────────────────────

class AgentExecutionContext:
    """
    Wrapper de ejecución para agentes agenticos de NEXUS.

    Gestiona el ciclo de vida completo de una ejecución:
      - Abre una traza (trace_id único)
      - Evalúa guardrails antes de cada acción
      - Ejecuta o pausa según el veredicto
      - Registra timing, resultado e interpretación
      - Cierra la traza con conclusión y estado final

    Los agentes reciben este contexto inyectado desde el orquestador.
    Si no se inyecta, el comportamiento legacy sigue funcionando.
    """

    # Máximo de caracteres del output capturado por paso (evita saturar contexto)
    _MAX_RESULT_CHARS = 3000

    def __init__(
        self,
        *,
        triggered_by: str,
        agent_name: str,
        model_used: str = "unknown",
        model_tier: int = 1,
        audit_id: str | None = None,
        input_summary: str = "",
        guardrails: GuardrailEngine | None = None,
    ) -> None:
        self.trace_id    = f"trace-{uuid.uuid4().hex[:12]}"
        self.audit_id    = audit_id or f"audit-{uuid.uuid4().hex[:12]}"
        self._agent      = agent_name
        self._user       = triggered_by
        self._model      = model_used
        self._tier       = model_tier
        self._summary    = input_summary
        self._steps:     list[ReasoningStep] = []
        self._counter    = 0
        self._started    = datetime.now(timezone.utc).isoformat()
        self._guardrails = guardrails or GuardrailEngine()

        logger.debug(
            "AgentExecutionContext abierto | trace={} | agent={} | user={}",
            self.trace_id, agent_name, triggered_by,
        )

    # ── Ejecución de pasos ────────────────────────────────────────────────────

    async def execute_step(
        self,
        *,
        thought: str,
        action: str,
        executor: Callable[[], str] | Callable[[], Awaitable[str]],
        observation_fn: Callable[[str], str] | None = None,
    ) -> ReasoningStep:
        """
        Ejecuta un paso con evaluación de guardrails.

        Args:
            thought:        Razonamiento del agente ("por qué hago esto")
            action:         Descripción legible de la acción / comando exacto
            executor:       Callable sync/async que ejecuta la acción real.
                            Si el veredicto es human_required o blocked, NO se llama.
            observation_fn: Función opcional para extraer observación del resultado.

        Returns:
            ReasoningStep con el veredicto, resultado y timing.
        """
        self._counter += 1
        num = self._counter

        verdict: GuardrailVerdict = self._guardrails.evaluate(action)

        logger.info(
            "AgentStep | trace={} | step={} | risk={} | verdict={} | action={}",
            self.trace_id, num,
            verdict.risk_class.value,
            verdict.verdict,
            action[:100],
        )

        # — BLOQUEADO: no ejecutar, registrar y continuar
        if verdict.verdict == "blocked":
            step = ReasoningStep(
                step=num,
                thought=thought,
                action=action,
                risk_class=verdict.risk_class,
                risk_score=verdict.risk_score,
                verdict="blocked",
                verdict_reason=verdict.reason,
                result="[BLOQUEADO — acción prohibida por política de seguridad]",
                observation="Esta acción está en la lista de prohibiciones absolutas y no puede ejecutarse.",
            )
            self._steps.append(step)
            return step

        # — REQUIERE HUMANO: no ejecutar, registrar como pendiente
        if verdict.verdict == "human_required":
            step = ReasoningStep(
                step=num,
                thought=thought,
                action=action,
                risk_class=verdict.risk_class,
                risk_score=verdict.risk_score,
                verdict="human_required",
                verdict_reason=verdict.reason,
                result="[EN COLA — pendiente de aprobación del operador]",
                observation="Acción pausada por guardrail. Un operador debe aprobarla antes de ejecutar.",
            )
            self._steps.append(step)
            return step

        # — AUTO-APROBADO: ejecutar
        t0 = time.monotonic()
        result_str: str
        error_str: str | None = None

        try:
            if inspect.iscoroutinefunction(executor):
                raw = await executor()
            else:
                raw = await asyncio.to_thread(executor)
            result_str = str(raw)[: self._MAX_RESULT_CHARS]
        except Exception as exc:
            result_str = f"[ERROR: {type(exc).__name__}: {exc}]"
            error_str  = str(exc)
            logger.warning(
                "AgentStep error | trace={} | step={} | {}",
                self.trace_id, num, exc,
            )

        duration_ms = int((time.monotonic() - t0) * 1000)
        observation = observation_fn(result_str) if observation_fn and not error_str else None

        step = ReasoningStep(
            step=num,
            thought=thought,
            action=action,
            risk_class=verdict.risk_class,
            risk_score=verdict.risk_score,
            verdict="auto_approved",
            verdict_reason=verdict.reason,
            result=result_str,
            observation=observation,
            duration_ms=duration_ms,
            error=error_str,
        )
        self._steps.append(step)
        return step

    def add_observation(self, thought: str, observation: str) -> ReasoningStep:
        """
        Añade un paso de solo razonamiento sin acción externa.
        Útil para que el agente registre inferencias intermedias.
        """
        self._counter += 1
        step = ReasoningStep(
            step=self._counter,
            thought=thought,
            action="[internal_reasoning]",
            risk_class=RiskClass.READ,
            risk_score=0.0,
            verdict="auto_approved",
            verdict_reason="Paso de razonamiento interno — sin acción externa",
            result=None,
            observation=observation,
        )
        self._steps.append(step)
        return step

    # ── Cierre ────────────────────────────────────────────────────────────────

    def finalize(
        self,
        conclusion: str,
        final_status: str | None = None,
    ) -> AgentTrace:
        """
        Cierra el contexto y devuelve la traza completa.
        final_status se infiere automáticamente si no se pasa:
          - blocked          → si hay pasos bloqueados
          - pending_approval → si hay pasos human_required sin aprobar
          - completed        → en cualquier otro caso
        """
        if final_status is None:
            if any(s.verdict == "blocked" for s in self._steps):
                final_status = "blocked"
            elif any(s.verdict == "human_required" and not s.approved_by for s in self._steps):
                final_status = "pending_approval"
            else:
                final_status = "completed"

        trace = AgentTrace(
            trace_id=self.trace_id,
            audit_id=self.audit_id,
            agent=self._agent,
            model_used=self._model,
            model_tier=self._tier,
            triggered_by=self._user,
            started_at=self._started,
            completed_at=datetime.now(timezone.utc).isoformat(),
            input_summary=self._summary,
            steps=list(self._steps),
            conclusion=conclusion,
            final_status=final_status,
        )

        logger.info(
            "AgentTrace finalizado | trace={} | status={} | steps={} | risk={}",
            trace.trace_id,
            trace.final_status,
            len(trace.steps),
            trace.highest_risk_class.value,
        )
        return trace

    # ── Propiedades de estado ─────────────────────────────────────────────────

    @property
    def steps(self) -> list[ReasoningStep]:
        return list(self._steps)

    @property
    def has_pending_approvals(self) -> bool:
        return any(s.verdict == "human_required" and not s.approved_by for s in self._steps)

    @property
    def is_blocked(self) -> bool:
        return any(s.verdict == "blocked" for s in self._steps)

    @property
    def completed_steps(self) -> list[ReasoningStep]:
        return [s for s in self._steps if s.verdict == "auto_approved"]
