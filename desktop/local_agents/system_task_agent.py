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
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.system_task_agent")

_MAX_LOOP_STEPS = 6

# Timeout para el script YA CONFIRMADO por el usuario (no el de _run_powershell
# por defecto, 60s, pensado para diagnosticos ligeros). Una tarea real como
# "busca en todo el disco C: los PDF que contengan X" puede tardar varios
# minutos de I/O legitimo — bug real: un usuario confirmo un rastreo de disco
# completo y murio con "tardo demasiado" a los 60s, sin ningun resultado
# parcial ni forma de saber que estaba genuinamente trabajando.
_CONFIRMED_SCRIPT_TIMEOUT = 600.0

# Parsea el script con el propio parser de PowerShell (no regex) y comprueba
# con Get-Command que cada cmdlet referenciado existe de verdad en esta
# maquina. Nunca escribe el script del usuario dentro de este string — lo
# lee de un fichero temporal via $env:NEXUS_SCRIPT_PATH para no depender de
# escapar comillas/heredocs ajenos.
_VALIDATE_SCRIPT_PS = r"""
$scriptText = Get-Content -LiteralPath $env:NEXUS_SCRIPT_PATH -Raw
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptText, [ref]$tokens, [ref]$parseErrors)
$commands = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $true) |
    ForEach-Object { $_.GetCommandName() } | Where-Object { $_ } | Sort-Object -Unique
$missing = @()
foreach ($c in $commands) {
    if (-not (Get-Command -Name $c -ErrorAction SilentlyContinue)) { $missing += $c }
}
[PSCustomObject]@{
    missing = @($missing)
    parse_errors = @($parseErrors | ForEach-Object { $_.Message })
} | ConvertTo-Json -Compress
"""

# Whitelist fijo de solo lectura para investigar el PC local antes de
# proponer nada — mismo principio que el whitelist SSH de RemoteOpsAgent.
# Nunca comandos que decida el LLM: el "sin confirmar" solo es una garantia
# real si el conjunto de comandos esta cerrado de antemano.
_LOCAL_DIAGNOSTIC_COMMANDS: list[tuple[str, str]] = [
    (
        "Get-CimInstance Win32_OperatingSystem | Select-Object LastBootUpTime, "
        "@{N='FreeMemMB';E={[math]::Round($_.FreePhysicalMemory/1KB,0)}}, "
        "@{N='TotalMemMB';E={[math]::Round($_.TotalVisibleMemorySize/1KB,0)}} | Format-List | Out-String -Width 200",
        "Arranque y memoria",
    ),
    (
        "Get-Process | Sort-Object CPU -Descending | Select-Object -First 8 Name, "
        "@{N='CPU_s';E={[math]::Round($_.CPU,1)}}, Id | Format-Table -AutoSize | Out-String -Width 200",
        "Top procesos por CPU",
    ),
    (
        "Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 8 Name, "
        "@{N='MemMB';E={[math]::Round($_.WorkingSet/1MB,0)}}, Id | Format-Table -AutoSize | Out-String -Width 200",
        "Top procesos por memoria",
    ),
    (
        "Get-PSDrive -PSProvider FileSystem | Where-Object { $null -ne $_.Used } | Select-Object Name, "
        "@{N='FreeGB';E={[math]::Round($_.Free/1GB,1)}}, @{N='UsedGB';E={[math]::Round($_.Used/1GB,1)}} | "
        "Format-Table -AutoSize | Out-String -Width 200",
        "Espacio en disco",
    ),
    (
        "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average",
        "Uso de CPU actual (%)",
    ),
]

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
            "name": "run_diagnostic",
            "description": (
                "Ejecuta un diagnostico real de solo lectura en este PC (procesos por "
                "CPU/memoria, disco, uptime) SIN pedir confirmacion — nunca cambia nada. "
                "Usalo SIEMPRE antes de proponer una accion para un sintoma vago (va "
                "lento, se cuelga, no responde, esta raro) en vez de adivinar la causa o "
                "saltar directo a algo drastico como reiniciar el equipo."
            ),
            "parameters": {"type": "object", "properties": {}},
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


def _run_powershell(
    script: str, *, timeout: float = 60.0, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class SystemTaskAgent:
    """Resuelve tareas libres sobre el PC via skill guardada, bucle de tools o windows-use."""

    persistence_key = "system_task"

    def __init__(self, cfg, *, llm_router=None, skill_library=None, cmdb=None, store=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._skill_library = skill_library
        self._cmdb = cmdb
        self._store = store
        self._agent = None
        self._pending: dict[str, PendingSystemTask] = {}

    # ── Persistencia (ver desktop/storage/pending_actions.py) ───────────────

    def _set_pending(self, context_id: str, pending: PendingSystemTask) -> None:
        self._pending[context_id] = pending
        if self._store is not None:
            payload = {
                "skill_id": pending.skill_id, "script": pending.script,
                "verify_command": pending.verify_command, "description": pending.description,
            }
            self._store.save(
                agent_id=self.persistence_key, context_id=context_id, kind=pending.kind,
                task=pending.task, payload=payload, messages=pending.messages,
                tool_call_id=pending.tool_call_id,
            )

    def _clear_pending(self, context_id: str) -> PendingSystemTask | None:
        pending = self._pending.pop(context_id, None)
        if self._store is not None:
            self._store.delete(agent_id=self.persistence_key, context_id=context_id)
        return pending

    def load_pending_from_store(self) -> None:
        if self._store is None:
            return
        for row in self._store.list_for_agent(self.persistence_key):
            self._pending[row.context_id] = PendingSystemTask(
                task=row.task, kind=row.kind, messages=row.messages, tool_call_id=row.tool_call_id,
                skill_id=row.payload.get("skill_id"), script=row.payload.get("script"),
                verify_command=row.payload.get("verify_command"), description=row.payload.get("description"),
            )

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
        from nexus.cmdb.lookup import search_devices

        try:
            return await search_devices(self._cmdb, query)
        except Exception:
            logger.exception("Fallo consultando CMDB")
            return "Error consultando el CMDB."

    # ── Tool: run_diagnostic (solo lectura, sin confirmar) ──────────────────

    async def _run_diagnostic(self) -> str:
        sections: list[str] = []
        for cmd, label in _LOCAL_DIAGNOSTIC_COMMANDS:
            try:
                result = await asyncio.to_thread(_run_powershell, cmd, timeout=15.0)
                output = (result.stdout or "").strip() or "(sin datos)"
                sections.append(f"### {label}\n{output}")
            except Exception as exc:
                sections.append(f"### {label}\n[error: {exc}]")
        return "\n\n".join(sections)

    # ── Validacion: cmdlets reales antes de confirmar ───────────────────────

    async def _validate_script(self, script: str) -> list[str]:
        """Comprueba con Get-Command que cada cmdlet del script existe de
        verdad en esta maquina — nunca deja llegar a confirmacion (ni a
        reutilizarse desde SkillLibrary) un script con cmdlets inventados."""
        if not script.strip():
            return []

        fd, path = tempfile.mkstemp(suffix=".txt", prefix="nexus_script_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(script)
            env = {**os.environ, "NEXUS_SCRIPT_PATH": path}
            result = await asyncio.to_thread(_run_powershell, _VALIDATE_SCRIPT_PS, timeout=20.0, env=env)
        except Exception:
            logger.exception("Fallo validando el script generado")
            return []
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        problems: list[str] = []
        for cmdlet in data.get("missing") or []:
            problems.append(f"El cmdlet '{cmdlet}' no existe en este sistema.")
        for err in data.get("parse_errors") or []:
            problems.append(f"Error de sintaxis: {err}")
        return problems

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

            # El modelo a veces pide varias herramientas a la vez en un mismo turno.
            # Solo actuamos sobre la primera, pero la API exige una respuesta "tool"
            # por CADA tool_call_id del turno o el siguiente request devuelve 400.
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

            if name == "lookup_cmdb":
                result_text = await self._lookup_cmdb(args.get("query", ""))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
                continue

            if name == "run_diagnostic":
                result_text = await self._run_diagnostic()
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
                script = args.get("script", "")
                problems = await self._validate_script(script)
                if problems:
                    feedback = (
                        "El script propuesto NO es valido y no se ha mostrado al usuario:\n- "
                        + "\n- ".join(problems)
                        + "\nCorrigelo usando solo cmdlets reales de PowerShell y vuelve a llamar a run_script."
                    )
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": feedback})
                    continue
                return {
                    "kind": "run_script",
                    "script": script,
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
            self._set_pending(context_id, PendingSystemTask(
                task=task, kind="ask_user", messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
            ))
            return {"kind": "ask_user", "task": task, "question": outcome["question"]}

        if kind == "run_script":
            self._set_pending(context_id, PendingSystemTask(
                task=task, kind="run_script", messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
                script=outcome["script"], verify_command=outcome.get("verify_command", ""),
                description=outcome.get("description", task),
            ))
            return {"kind": "run_script", "task": task, "script": outcome["script"], "description": outcome.get("description", task)}

        # finish
        if not outcome.get("scriptable", True):
            self._set_pending(context_id, PendingSystemTask(task=task, kind="windows_use"))
            return {"kind": "windows_use", "task": task}

        return {"kind": "finish", "task": task, "summary": outcome.get("summary", "Hecho.")}

    # ── API publica ──────────────────────────────────────────────────────────

    async def propose(
        self, context_id: str, task: str, *, history: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        """Decide como resolver la tarea. Puede terminar de una vez o dejarla pendiente."""
        if self._skill_library is not None and self._llm_router is not None:
            match = await self._skill_library.find_match(task, self._llm_router)
            if match is not None:
                problems = await self._validate_script(match.script_body)
                if not problems:
                    self._set_pending(context_id, PendingSystemTask(
                        task=task, kind="skill_match", skill_id=match.skill_id,
                        script=match.script_body, verify_command=match.verify_command,
                        description=match.description,
                    ))
                    return {
                        "kind": "skill_match", "task": task, "script": match.script_body,
                        "description": match.description, "status": match.status,
                    }
                logger.warning(
                    "Skill guardada '%s' ya no es valida (%s) — se regenera con el LLM",
                    match.skill_id, "; ".join(problems),
                )
                self._skill_library.record_failure(match.skill_id)

        if self._llm_router is None:
            self._set_pending(context_id, PendingSystemTask(task=task, kind="windows_use"))
            return {"kind": "windows_use", "task": task}

        # Igual que en RemoteOpsAgent: sin el historial previo, un mensaje de
        # seguimiento tipo "y ese proceso, mátalo" no tiene forma de saber a
        # que proceso se referia el turno anterior.
        seed_messages = [*(history or []), {"role": "user", "content": task}]
        outcome = await self._run_loop(seed_messages)
        return self._store_outcome(context_id, task, outcome)

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    async def list_pending(self) -> list[dict[str, Any]]:
        """Solo lectura, para el gestor de agentes — nunca expone el script en claro
        para pendientes ajenos, solo la descripcion/tarea.

        Async por consistencia con el resto de agentes (ver mouse_agent.py)."""
        return [
            {
                "context_id": context_id,
                "agent_id": "system_task",
                "kind": pending.kind,
                "summary": pending.description or pending.task,
            }
            for context_id, pending in self._pending.items()
        ]

    def pending_kind(self, context_id: str) -> str | None:
        pending = self._pending.get(context_id)
        return pending.kind if pending else None

    def cancel(self, context_id: str) -> None:
        self._clear_pending(context_id)

    async def _run_script_and_record(self, pending: PendingSystemTask) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                _run_powershell, pending.script, timeout=_CONFIRMED_SCRIPT_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            minutes = int(_CONFIRMED_SCRIPT_TIMEOUT // 60)
            return {
                "task": pending.task,
                "is_done": False,
                "content": None,
                "error": (
                    f"El script llevaba mas de {minutes} minutos corriendo y lo he parado. "
                    "Si es un rastreo de disco completo, prueba a acotarlo a una carpeta "
                    "concreta en vez de todo el disco — sera mucho mas rapido."
                ),
            }

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

        from utils.logger import hito
        hito(
            "pepo.system_task | tarea=\"{tarea}\" | modo={modo} | resultado={resultado}",
            tarea=pending.task[:120], modo=pending.kind, resultado="OK" if success else f"FALLO: {error}",
        )

        return {"task": pending.task, "is_done": success, "content": "\n".join(content_parts), "error": error}

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any] | None:
        """Continua/ejecuta lo pendiente. `user_reply` es obligatorio si el pendiente es 'ask_user'."""
        pending = self._clear_pending(context_id)
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
