"""
desktop/local_agents/system_task_agent.py
--------------------------------------------
SystemTaskAgent — cajon general para que PEPO toque el PC.

Bucle generico con tool calling: el LLM descompone CUALQUIER tarea usando
un juego de herramientas fijo (lookup_cmdb, ask_user, run_script, finish),
sin que haya codigo Python distinto por cada tipo de incidencia. El
determinismo no viene de precodificar los pasos — viene de que el toolbox
y el bucle de orquestacion son siempre los mismos; lo unico que cambia por
tarea es que datos rellena el LLM.

- lookup_cmdb: se ejecuta solo, sin confirmar (lectura, sin efectos).
- ask_user: pausa el bucle y pregunta; la respuesta libre del usuario
  entra como resultado de esa herramienta y el bucle continua.
- run_script: pausa el bucle pidiendo confirmacion humana antes de tocar
  nada; si el resultado verifica bien, se guarda en SkillLibrary.
- finish: termina. Si dice que no es scriptable, cae a windows-use (la
  red de seguridad para lo que de verdad requiere manejar la GUI).

Antes de entrar al bucle se comprueba si ya hay una skill guardada que
resuelva la misma tarea — si la hay, se reutiliza sin pasar por el LLM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.system_task_agent")

_MAX_LOOP_STEPS = 6

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_cmdb",
            "description": (
                "Busca datos conocidos en el inventario de Nexus (CMDB): servidores, "
                "dispositivos, roles, IPs, notas. Usalo para resolver cualquier dato "
                "que la tarea necesite antes de suponerlo o de preguntar al usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Que se busca (nombre, IP, rol, tipo...)"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pregunta al usuario UN dato imprescindible que no se ha podido resolver "
                "de otra forma (ni por el mensaje original, ni por lookup_cmdb). Una sola "
                "pregunta concreta cada vez."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_script",
            "description": (
                "Propone un script de PowerShell para resolver la tarea, pendiente de "
                "confirmacion humana antes de ejecutarse. Usalo cuando ya tengas todos "
                "los datos que hacen falta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string"},
                    "verify_command": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "Descripcion generica y reutilizable de lo que hace, sin datos especificos de esta ejecucion salvo que sean el objetivo mismo.",
                    },
                },
                "required": ["script", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Termina: la tarea ya esta resuelta con lo que sabes, o no se puede "
                "continuar sin mas informacion, o no es posible resolverla por script."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "scriptable": {
                        "type": "boolean",
                        "description": "false si la tarea requiere manejar una GUI sin cmdlet equivalente",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


@dataclass(slots=True)
class PendingSystemTask:
    task: str
    kind: str  # "skill_match" | "ask_user" | "run_script" | "windows_use"
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    skill_id: str | None = None
    script: str | None = None
    verify_command: str | None = None
    description: str | None = None


def _run_powershell(script: str, *, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class SystemTaskAgent:
    """Resuelve tareas libres sobre el PC via skill guardada, bucle de tools o windows-use."""

    def __init__(self, cfg, *, llm_router=None, skill_library=None, cmdb=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._skill_library = skill_library
        self._cmdb = cmdb
        self._agent = None
        self._pending: dict[str, PendingSystemTask] = {}

    def _get_windows_use_agent(self):
        if self._agent is None:
            from windows_use import Agent
            from windows_use.providers.open_router import ChatOpenRouter

            llm = ChatOpenRouter(
                model=self._cfg.llm_l2_model,
                api_key=self._cfg.llm_l2_key,
                base_url=self._cfg.llm_l2_url or "https://openrouter.ai/api/v1",
            )
            self._agent = Agent(llm=llm, use_vision=False, log_to_console=False)
        return self._agent

    # ── Tool: lookup_cmdb ────────────────────────────────────────────────────

    async def _lookup_cmdb(self, query: str) -> str:
        if self._cmdb is None:
            return "CMDB no disponible."
        try:
            devices = await self._cmdb.list_devices(enabled_only=False)
        except Exception:
            logger.exception("Fallo consultando CMDB")
            return "Error consultando el CMDB."

        needle = (query or "").strip().lower()
        if not needle:
            return "Consulta vacia."

        hits = []
        for d in devices:
            haystack = " ".join(
                str(v) for v in (d.name, d.ip, d.type, d.vendor, d.notes, d.fqdn) if v
            ).lower()
            haystack += " " + " ".join(f"{k}:{v}" for k, v in (d.tags or {}).items()).lower()
            if needle in haystack:
                hits.append(f"{d.name} (ip={d.ip}, tipo={d.type}, notas={d.notes or '-'})")

        if not hits:
            return f"No hay ningun dispositivo en el CMDB que coincida con '{query}'."
        return "Encontrado en el CMDB:\n" + "\n".join(hits[:5])

    # ── Bucle generico ───────────────────────────────────────────────────────

    async def _run_loop(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        from nexus.prompts import resolve_prompt_sync

        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": resolve_prompt_sync("pepo.system_task_loop")}, *messages]

        for _ in range(_MAX_LOOP_STEPS):
            try:
                response = await self._llm_router.call(
                    messages=messages,
                    tools=_TOOLS,
                    tool_choice="auto",
                    preferred_level=2,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=30.0,
                )
            except Exception as exc:
                logger.exception("Fallo en el bucle de tarea de sistema")
                return {"kind": "finish", "summary": f"No pude continuar: {exc}"}

            if response.error:
                return {"kind": "finish", "summary": f"No pude continuar: {response.error}"}

            if not response.tool_calls:
                return {"kind": "finish", "summary": response.content or "Hecho."}

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
                "tool_calls": [call],
            })

            if name == "lookup_cmdb":
                result_text = await self._lookup_cmdb(args.get("query", ""))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
                continue

            if name == "ask_user":
                return {
                    "kind": "ask_user",
                    "question": args.get("question", "?"),
                    "messages": messages,
                    "tool_call_id": call.get("id", ""),
                }

            if name == "run_script":
                return {
                    "kind": "run_script",
                    "script": args.get("script", ""),
                    "verify_command": args.get("verify_command", ""),
                    "description": args.get("description", ""),
                    "messages": messages,
                    "tool_call_id": call.get("id", ""),
                }

            if name == "finish":
                return {
                    "kind": "finish",
                    "summary": args.get("summary", "Hecho."),
                    "scriptable": args.get("scriptable", True),
                }

            return {"kind": "finish", "summary": f"Herramienta desconocida: {name}"}

        return {"kind": "finish", "summary": "No he podido resolverlo en los pasos disponibles."}

    def _store_outcome(self, context_id: str, task: str, outcome: dict[str, Any]) -> dict[str, Any]:
        kind = outcome["kind"]

        if kind == "ask_user":
            self._pending[context_id] = PendingSystemTask(
                task=task, kind="ask_user", messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
            )
            return {"kind": "ask_user", "task": task, "question": outcome["question"]}

        if kind == "run_script":
            self._pending[context_id] = PendingSystemTask(
                task=task, kind="run_script", messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
                script=outcome["script"], verify_command=outcome.get("verify_command", ""),
                description=outcome.get("description", task),
            )
            return {"kind": "run_script", "task": task, "script": outcome["script"], "description": outcome.get("description", task)}

        # finish
        if not outcome.get("scriptable", True):
            self._pending[context_id] = PendingSystemTask(task=task, kind="windows_use")
            return {"kind": "windows_use", "task": task}

        return {"kind": "finish", "task": task, "summary": outcome.get("summary", "Hecho.")}

    # ── API publica ──────────────────────────────────────────────────────────

    async def propose(self, context_id: str, task: str) -> dict[str, Any]:
        """Decide como resolver la tarea. Puede terminar de una vez o dejarla pendiente."""
        if self._skill_library is not None and self._llm_router is not None:
            match = await self._skill_library.find_match(task, self._llm_router)
            if match is not None:
                self._pending[context_id] = PendingSystemTask(
                    task=task, kind="skill_match", skill_id=match.skill_id,
                    script=match.script_body, verify_command=match.verify_command,
                    description=match.description,
                )
                return {
                    "kind": "skill_match", "task": task, "script": match.script_body,
                    "description": match.description, "status": match.status,
                }

        if self._llm_router is None:
            self._pending[context_id] = PendingSystemTask(task=task, kind="windows_use")
            return {"kind": "windows_use", "task": task}

        outcome = await self._run_loop([{"role": "user", "content": task}])
        return self._store_outcome(context_id, task, outcome)

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    def pending_kind(self, context_id: str) -> str | None:
        pending = self._pending.get(context_id)
        return pending.kind if pending else None

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)

    async def _run_script_and_record(self, pending: PendingSystemTask) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(_run_powershell, pending.script)
        except subprocess.TimeoutExpired:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El script tardo demasiado (timeout)."}

        success = result.returncode == 0
        verify_output = ""
        if success and pending.verify_command:
            try:
                verify = await asyncio.to_thread(_run_powershell, pending.verify_command, timeout=20.0)
                verify_output = (verify.stdout or "").strip()
            except subprocess.TimeoutExpired:
                verify_output = "(verificacion sin respuesta)"

        if self._skill_library is not None:
            if pending.kind == "skill_match" and pending.skill_id:
                if success:
                    self._skill_library.record_success(pending.skill_id)
                else:
                    self._skill_library.record_failure(pending.skill_id)
            elif pending.kind == "run_script" and success:
                self._skill_library.save_skill(
                    description=pending.description or pending.task,
                    script_body=pending.script,
                    verify_command=pending.verify_command or "",
                )

        content_parts = [(result.stdout or "").strip() or "Hecho."]
        if verify_output:
            content_parts.append(f"Verificacion: {verify_output}")
        error = None if success else ((result.stderr or "").strip() or f"El script devolvio codigo {result.returncode}.")

        return {"task": pending.task, "is_done": success, "content": "\n".join(content_parts), "error": error}

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any] | None:
        """Continua/ejecuta lo pendiente. `user_reply` es obligatorio si el pendiente es 'ask_user'."""
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return None

        if pending.kind in ("skill_match", "run_script"):
            logger.info("Ejecutando script de sistema | modo=%s | tarea=%s", pending.kind, pending.task)
            result = await self._run_script_and_record(pending)
            logger.info("Script de sistema terminado | is_done=%s | error=%s", result["is_done"], result["error"])
            return result

        if pending.kind == "ask_user":
            pending.messages.append({
                "role": "tool", "tool_call_id": pending.tool_call_id, "content": user_reply or "",
            })
            outcome = await self._run_loop(pending.messages)
            stored = self._store_outcome(context_id, pending.task, outcome)
            if stored["kind"] == "finish":
                return {"task": pending.task, "is_done": True, "content": stored["summary"], "error": None}
            if stored["kind"] == "ask_user":
                return {"task": pending.task, "is_done": False, "content": None, "error": None, "next_question": stored["question"]}
            if stored["kind"] == "run_script":
                return {"task": pending.task, "is_done": False, "content": None, "error": None, "next_script": stored["script"], "next_description": stored["description"]}
            if stored["kind"] == "windows_use":
                return await self._run_windows_use(pending.task)

        agent_kind = pending.kind
        if agent_kind == "windows_use":
            return await self._run_windows_use(pending.task)

        return None

    async def _run_windows_use(self, task: str) -> dict[str, Any]:
        agent = self._get_windows_use_agent()
        logger.info("Ejecutando tarea de sistema via windows-use | tarea=%s", task)
        result = await agent.ainvoke(task)
        logger.info("Tarea de sistema terminada | is_done=%s | error=%s", result.is_done, result.error)
        return {"task": task, "is_done": result.is_done, "content": result.content, "error": result.error}
