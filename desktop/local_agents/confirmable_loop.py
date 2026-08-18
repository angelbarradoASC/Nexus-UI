"""
desktop/local_agents/confirmable_loop.py
--------------------------------------------
ConfirmableAgent — bucle de tool-calling compartido por los agentes de PEPO
que proponen algo y esperan confirmacion humana antes de ejecutarlo
(RemoteOpsAgent, SelfConfigAgent). Antes cada uno reimplementaba su propio
_run_loop/_store_outcome/PendingX casi identicos (~250 lineas duplicadas) —
extraido tras construir SelfConfigAgent copiando RemoteOpsAgent case por
caso. Inspirado en como OpenWorker (andrewyng/openworker) separa "el bucle"
(un motor) de "las skills" (datos que el motor consume), aunque escrito
desde cero para las convenciones de este proyecto.

Las subclases solo aportan:
- `tools`: sus tools especificas (ademas de ask_user/ask_user_secret/finish,
  ya incluidas aqui — nunca las redefinan).
- `prompt_key`: la entrada del catalogo de prompts (app/nexus/prompts/
  catalogue.py) para el system prompt del bucle.
- `agent_id`: identificador corto para list_pending()/el gestor de agentes.
- `dispatch_tool(name, args)`: que hacer con cada tool propia — devuelve un
  string (resultado de una tool de solo lectura, el bucle continua) o un
  ProposalOutcome (la tool propone algo que requiere confirmacion, el
  bucle para aqui).
- `execute(pending)`: que hacer al confirmar una ProposalOutcome ya
  aprobada por el usuario — la unica pieza que de verdad escribe/actua.
- `describe_pending(pending)` (opcional): resumen mas rico que pending.task
  para list_pending(), si la subclase lo necesita.

Seguridad (ver self_config_agent.py, donde se descubrio en verificacion
manual): el LLM no siempre respeta la instruccion de usar ask_user_secret
para datos sensibles — a veces contesta en texto libre sin llamar a ninguna
tool. Este bucle aplica DOS redes de seguridad, no solo la instruccion del
prompt: (1) si el texto de una pregunta suena a secreto, se reclasifica
como ask_user_secret aunque el LLM haya llamado a ask_user; (2) si el LLM
no llama a NINGUNA tool pero el texto suena a que esta pidiendo un dato
(pregunta o instruccion imperativa), se trata como un ask_user implicito en
vez de darlo por terminado — si no, se pierde el estado pendiente.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.confirmable_agent")

_SECRET_QUESTION_PATTERN = re.compile(
    r"contrase|password|\btoken\b|clave|secreto|\bsecret\b|api[\s_-]?key",
    re.IGNORECASE,
)

# Heuristica para reconocer que una respuesta en texto libre (sin tool call)
# le esta pidiendo un dato al usuario en vez de dar una respuesta final.
# Probado con el modelo real: no siempre termina en "?" — a veces es una
# orden imperativa terminada en ":" ("...ingresa la contraseña:").
_FOLLOWUP_QUESTION_PATTERN = re.compile(
    r"[?:]\s*$|^(por favor|necesito|podr[ií]as|ind[ií]came|dime|cu[aá]l es|introduce|ingresa|proporciona|facilita)",
    re.IGNORECASE,
)

_ASK_KINDS = {"ask_user", "ask_user_secret"}

_BASE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pregunta al usuario UN dato NO sensible que falte. Nunca uses esto "
                "para contraseñas, tokens o claves — para eso usa ask_user_secret."
            ),
            "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user_secret",
            "description": (
                "Identica a ask_user, pero UNICAMENTE para datos sensibles (contraseña, "
                "token, clave). Marca la respuesta para que no quede en texto plano en "
                "el historial de conversaciones."
            ),
            "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Termina: ya se ha respondido con lo que sabes (incluye respuestas "
                "negativas o 'no soportado' como respuestas finales validas, no fallos)."
            ),
            "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
        },
    },
]


@dataclass(slots=True)
class ProposalOutcome:
    """Lo que devuelve dispatch_tool() cuando su tool propone algo que
    requiere confirmacion humana — el bucle para aqui, nunca escribe nada
    todavia."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingAction:
    task: str
    kind: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class ConfirmableAgent:
    """Bucle generico de tool-calling con confirmacion humana en dos pasos.

    Subclases: RemoteOpsAgent, SelfConfigAgent, MCPAgent."""

    tools: list[dict[str, Any]] = []
    prompt_key: str = ""
    agent_id: str = "confirmable"
    max_loop_steps: int = 6

    # Identidad FIJA para persistencia — a diferencia de `agent_id` (que
    # MCPAgent muta en tiempo real segun el servidor activo), esta nunca
    # cambia, para poder encontrar el pendiente guardado sin importar el
    # modo en el que estaba el agente cuando se guardo. Cada subclase la
    # fija; si queda vacia, la persistencia queda desactivada (compatibilidad
    # con tests que construyen el agente sin store).
    persistence_key: str = ""

    def __init__(self, cfg, *, llm_router=None, store=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._store = store
        self._pending: dict[str, PendingAction] = {}

    # ── Persistencia (ver desktop/storage/pending_actions.py) ───────────────

    def _persist(self, context_id: str, pending: PendingAction) -> None:
        if self._store is None or not self.persistence_key:
            return
        self._store.save(
            agent_id=self.persistence_key,
            context_id=context_id,
            kind=pending.kind,
            task=pending.task,
            payload=pending.payload,
            messages=pending.messages,
            tool_call_id=pending.tool_call_id,
        )

    def _forget(self, context_id: str) -> None:
        if self._store is None or not self.persistence_key:
            return
        self._store.delete(agent_id=self.persistence_key, context_id=context_id)

    def load_pending_from_store(self) -> None:
        """Rehidrata `self._pending` desde el store al arrancar — sin esto,
        un pendiente que sobrevivio a un reinicio del proceso queda huerfano
        en SQLite pero invisible para has_pending()/list_pending()."""
        if self._store is None or not self.persistence_key:
            return
        for row in self._store.list_for_agent(self.persistence_key):
            self._pending[row.context_id] = PendingAction(
                task=row.task, kind=row.kind, messages=row.messages,
                tool_call_id=row.tool_call_id, payload=row.payload,
            )

    # ── Hooks para las subclases ─────────────────────────────────────────────

    async def dispatch_tool(self, name: str, args: dict[str, Any]) -> str | ProposalOutcome | None:
        """Devuelve el resultado (string) de una tool de solo lectura propia,
        o una ProposalOutcome si la tool propone algo pendiente de confirmar.
        None si la tool no existe."""
        raise NotImplementedError

    async def execute(self, pending: PendingAction) -> dict[str, Any]:
        """Ejecuta lo que quedo pendiente tras confirmar. Debe devolver
        {"task", "is_done", "content", "error"}."""
        raise NotImplementedError

    def describe_pending(self, pending: PendingAction) -> str:
        """Resumen para list_pending() — override si pending.task no basta."""
        return pending.task

    # ── Bucle generico ───────────────────────────────────────────────────────

    async def _run_loop(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        from nexus.prompts import resolve_prompt_sync

        all_tools = [*_BASE_TOOLS, *self.tools]

        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": resolve_prompt_sync(self.prompt_key)}, *messages]

        for _ in range(self.max_loop_steps):
            try:
                response = await self._llm_router.call(
                    messages=messages,
                    tools=all_tools,
                    tool_choice="auto",
                    preferred_level=2,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=30.0,
                )
            except Exception as exc:
                logger.exception("Fallo en el bucle de %s", self.agent_id)
                return {"kind": "finish", "summary": f"No pude continuar: {exc}"}

            if response.error:
                return {"kind": "finish", "summary": f"No pude continuar: {response.error}"}

            if not response.tool_calls:
                content = response.content or ""
                stripped = content.strip()
                if stripped and _FOLLOWUP_QUESTION_PATTERN.search(stripped):
                    messages.append({"role": "assistant", "content": content})
                    return {"kind": "ask_user", "question": stripped, "messages": messages, "tool_call_id": None}
                return {"kind": "finish", "summary": content or "Hecho."}

            call = response.tool_calls[0]
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            messages.append({
                "role": "assistant",
                "content": response.content or None,
                "tool_calls": response.tool_calls,
            })
            for extra_call in response.tool_calls[1:]:
                messages.append({
                    "role": "tool", "tool_call_id": extra_call.get("id", ""),
                    "content": "Ignorada — ya se proceso otra herramienta en este turno.",
                })

            if name in _ASK_KINDS:
                return {"kind": name, "question": args.get("question", "?"), "messages": messages, "tool_call_id": call.get("id", "")}

            if name == "finish":
                return {"kind": "finish", "summary": args.get("summary", "Hecho.")}

            result = await self.dispatch_tool(name, args)
            if isinstance(result, ProposalOutcome):
                return {"kind": result.kind, "payload": result.payload, "messages": messages, "tool_call_id": call.get("id", "")}
            if result is None:
                return {"kind": "finish", "summary": f"Herramienta desconocida: {name}"}
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": str(result)})

        return {"kind": "finish", "summary": "No he podido resolverlo en los pasos disponibles."}

    def _store_outcome(self, context_id: str, task: str, outcome: dict[str, Any]) -> dict[str, Any]:
        kind = outcome["kind"]

        # Red de seguridad determinista: si el LLM pidio un dato via ask_user
        # (no ask_user_secret) pero el TEXTO de la pregunta suena a secreto,
        # se trata igualmente como ask_user_secret para la redaccion en el
        # historial — no depende solo de que el modelo eligiera bien la tool.
        if kind == "ask_user" and _SECRET_QUESTION_PATTERN.search(outcome.get("question", "")):
            kind = "ask_user_secret"

        if kind in _ASK_KINDS:
            pending = PendingAction(
                task=task, kind=kind, messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
            )
            self._pending[context_id] = pending
            self._persist(context_id, pending)
            return {"kind": kind, "task": task, "question": outcome["question"]}

        if kind == "finish":
            return {"kind": "finish", "task": task, "summary": outcome.get("summary", "Hecho.")}

        # cualquier otro kind viene de una ProposalOutcome de la subclase
        pending = PendingAction(
            task=task, kind=kind, messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
            payload=outcome.get("payload", {}),
        )
        self._pending[context_id] = pending
        self._persist(context_id, pending)
        return {"kind": kind, "task": task, "payload": outcome.get("payload", {})}

    # ── API publica ──────────────────────────────────────────────────────────

    async def propose(self, context_id: str, task: str, *, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        if self._llm_router is None:
            return {"kind": "finish", "task": task, "summary": "El razonamiento por LLM no esta disponible ahora mismo."}
        # El historial de la conversacion (turnos previos usuario/asistente) se
        # antepone a la tarea nueva — sin esto, una referencia como "esa IP"
        # en un mensaje de seguimiento no significa nada para el bucle.
        seed_messages = [*(history or []), {"role": "user", "content": task}]
        outcome = await self._run_loop(seed_messages)
        return self._store_outcome(context_id, task, outcome)

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    def pending_kind(self, context_id: str) -> str | None:
        pending = self._pending.get(context_id)
        return pending.kind if pending else None

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)
        self._forget(context_id)

    async def list_pending(self) -> list[dict[str, Any]]:
        """Solo lectura, para el gestor de agentes — nunca expone secretos ni
        credenciales (describe_pending() de cada subclase controla el texto)."""
        return [
            {
                "context_id": context_id,
                "agent_id": self.agent_id,
                "kind": pending.kind,
                "summary": self.describe_pending(pending),
            }
            for context_id, pending in self._pending.items()
        ]

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any] | None:
        """Continua/ejecuta lo pendiente. `user_reply` es obligatorio si el
        pendiente es 'ask_user'/'ask_user_secret'."""
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return None
        # Se olvida ya — si el bucle vuelve a dejar algo pendiente (otra
        # pregunta, u otra propuesta), _store_outcome() lo vuelve a guardar
        # con su propio payload; si no, la accion queda resuelta de verdad
        # (ejecutada o fallida) y no debe quedar nada huerfano en SQLite.
        self._forget(context_id)

        if pending.kind in _ASK_KINDS:
            if pending.tool_call_id:
                pending.messages.append({
                    "role": "tool", "tool_call_id": pending.tool_call_id, "content": user_reply or "",
                })
            else:
                # Pregunta en texto libre (sin tool call real detras) — ver
                # el branch "no tool_calls" de _run_loop. No hay tool_call_id
                # al que responder, asi que la respuesta entra como turno de
                # usuario normal.
                pending.messages.append({"role": "user", "content": user_reply or ""})
            outcome = await self._run_loop(pending.messages)
            stored = self._store_outcome(context_id, pending.task, outcome)
            if stored["kind"] == "finish":
                return {"task": pending.task, "is_done": True, "content": stored["summary"], "error": None}
            if stored["kind"] in _ASK_KINDS:
                return {
                    "task": pending.task, "is_done": False, "content": None, "error": None,
                    "next_kind": stored["kind"], "next_question": stored["question"],
                }
            return {
                "task": pending.task, "is_done": False, "content": None, "error": None,
                "next_kind": stored["kind"], "next_payload": stored.get("payload", {}),
            }

        # kind propio de la subclase — pendiente de ejecutar de verdad.
        return await self.execute(pending)
