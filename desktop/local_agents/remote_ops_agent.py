"""
desktop/local_agents/remote_ops_agent.py
--------------------------------------------
RemoteOpsAgent — hermano de SystemTaskAgent para infraestructura REMOTA
(servidores, no el PC local donde corre Nexus Desktop).

Mismo patron: bucle generico de tool-calling, el LLM decide que herramienta
llamar (lookup_cmdb, check_credentials, run_diagnostic, ask_user, finish).
El determinismo viene del toolbox + bucle, no de codigo distinto por
tecnologia — asi "BeaServer" se resuelve igual que cualquier otro nombre,
consultando el CMDB real en vez de adivinar por palabras clave del mensaje.

- lookup_cmdb: busca el dispositivo por nombre/ip/tipo en el CMDB real.
  Solo lectura, se ejecuta sin confirmar.
- check_credentials: comprueba si hay credenciales en el Vault para ese
  device_id (bloqueado / ausentes / presentes) SIN revelar el secreto.
  Solo lectura, se ejecuta sin confirmar.
- run_diagnostic: propone conectarse por SSH y ejecutar un whitelist fijo
  de comandos de solo lectura. Pendiente de confirmacion humana antes de
  abrir la conexion — igual que run_script pide confirmacion antes de
  tocar el PC local. Usa AgentAccessService (CMDB + Vault + SSHConnector
  ya resueltos) — nunca las credenciales viejas de CredentialStore.
- ask_user / finish: identico al patron de SystemTaskAgent.

Solo soporta management_protocol == "ssh" (lo unico que AgentAccessService
implementa hoy). Para otros protocolos responde con honestidad que no esta
soportado todavia — no se inventa una integracion que no existe.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.remote_ops_agent")

_MAX_LOOP_STEPS = 6

# Mismo whitelist de solo lectura que ya usaba el SSHAgent original —
# nunca comandos que escriban o modifiquen nada en el servidor destino.
_DIAGNOSTIC_COMMANDS: list[tuple[str, str]] = [
    ("uptime", "Uptime y carga"),
    ("free -m", "Memoria (MB)"),
    ("df -h", "Disco"),
    ("ps aux --sort=-%cpu | head -10", "Top 10 procesos por CPU"),
    (
        "journalctl -n 50 --no-pager 2>/dev/null || tail -n 50 /var/log/syslog 2>/dev/null",
        "Ultimas 50 lineas de log",
    ),
]

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_cmdb",
            "description": (
                "Busca un dispositivo real en el CMDB de Nexus por nombre, IP, tipo o "
                "notas. Usalo SIEMPRE antes de asumir que un servidor no existe o de "
                "preguntar al usuario que tecnologia es — el CMDB es la fuente de "
                "verdad, no lo adivines por el mensaje."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Nombre o pista del servidor, tal como lo dijo el usuario."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_credentials",
            "description": (
                "Comprueba si hay credenciales guardadas en el Vault para un device_id "
                "ya resuelto por lookup_cmdb. Nunca devuelve el secreto, solo si existen. "
                "Usalo antes de proponer un diagnostico, para no prometer algo que luego "
                "falle por falta de credenciales."
            ),
            "parameters": {
                "type": "object",
                "properties": {"device_id": {"type": "string"}},
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_diagnostic",
            "description": (
                "Propone conectarse por SSH a un dispositivo ya resuelto (con "
                "credenciales confirmadas) y ejecutar un diagnostico de solo lectura "
                "(uptime, memoria, disco, procesos, logs). Pendiente de confirmacion "
                "humana — nunca se conecta sin que el usuario diga que si."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "device_name": {"type": "string", "description": "Nombre legible del dispositivo, para el mensaje de confirmacion."},
                },
                "required": ["device_id", "device_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pregunta al usuario UN dato imprescindible que no se ha podido resolver "
                "por lookup_cmdb (por ejemplo, si hay varios dispositivos que coinciden "
                "y no esta claro cual). Una sola pregunta concreta cada vez."
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
            "name": "finish",
            "description": (
                "Termina: ya se ha respondido con lo que sabes (incluye el caso de "
                "'no encontrado en el CMDB' o 'sin credenciales en el Vault' — esos "
                "tambien son respuestas finales, no fallos)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]


@dataclass(slots=True)
class PendingRemoteOp:
    task: str
    kind: str  # "ask_user" | "run_diagnostic"
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    device_id: str | None = None
    device_name: str | None = None


class RemoteOpsAgent:
    """Resuelve preguntas sobre infraestructura remota via CMDB + Vault + SSH real."""

    def __init__(self, cfg, *, llm_router=None, cmdb=None, vault=None, access=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._cmdb = cmdb
        self._vault = vault
        self._access = access
        self._pending: dict[str, PendingRemoteOp] = {}

    # ── Tool: lookup_cmdb ────────────────────────────────────────────────────

    async def _lookup_cmdb(self, query: str) -> str:
        from nexus.cmdb.lookup import search_devices

        try:
            return await search_devices(self._cmdb, query)
        except Exception:
            logger.exception("Fallo consultando CMDB")
            return "Error consultando el CMDB."

    # ── Tool: check_credentials ──────────────────────────────────────────────

    async def _check_credentials(self, device_id: str) -> str:
        from nexus.vault.check import check_credentials

        return await check_credentials(self._vault, device_id)

    # ── Bucle generico ───────────────────────────────────────────────────────

    async def _run_loop(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        from nexus.prompts import resolve_prompt_sync

        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": resolve_prompt_sync("pepo.remote_ops_loop")}, *messages]

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
                logger.exception("Fallo en el bucle de operaciones remotas")
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

            if name == "check_credentials":
                result_text = await self._check_credentials(args.get("device_id", ""))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
                continue

            if name == "run_diagnostic":
                return {
                    "kind": "run_diagnostic",
                    "device_id": args.get("device_id", ""),
                    "device_name": args.get("device_name") or args.get("device_id", ""),
                    "messages": messages,
                    "tool_call_id": call.get("id", ""),
                }

            if name == "ask_user":
                return {
                    "kind": "ask_user",
                    "question": args.get("question", "?"),
                    "messages": messages,
                    "tool_call_id": call.get("id", ""),
                }

            if name == "finish":
                return {"kind": "finish", "summary": args.get("summary", "Hecho.")}

            return {"kind": "finish", "summary": f"Herramienta desconocida: {name}"}

        return {"kind": "finish", "summary": "No he podido resolverlo en los pasos disponibles."}

    def _store_outcome(self, context_id: str, task: str, outcome: dict[str, Any]) -> dict[str, Any]:
        kind = outcome["kind"]

        if kind == "ask_user":
            self._pending[context_id] = PendingRemoteOp(
                task=task, kind="ask_user", messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
            )
            return {"kind": "ask_user", "task": task, "question": outcome["question"]}

        if kind == "run_diagnostic":
            self._pending[context_id] = PendingRemoteOp(
                task=task, kind="run_diagnostic", messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
                device_id=outcome["device_id"], device_name=outcome["device_name"],
            )
            return {"kind": "run_diagnostic", "task": task, "device_id": outcome["device_id"], "device_name": outcome["device_name"]}

        return {"kind": "finish", "task": task, "summary": outcome.get("summary", "Hecho.")}

    # ── API publica ──────────────────────────────────────────────────────────

    async def propose(self, context_id: str, task: str, *, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        if self._llm_router is None:
            return {"kind": "finish", "task": task, "summary": "El razonamiento por LLM no esta disponible ahora mismo."}
        # El historial de la conversacion (turnos previos usuario/asistente) se
        # antepone a la tarea nueva — sin esto, "esa IP" o "el mismo servidor"
        # en un mensaje de seguimiento no significan nada para el bucle, que
        # arrancaria cada vez desde cero sin saber de que se hablaba antes.
        seed_messages = [*(history or []), {"role": "user", "content": task}]
        outcome = await self._run_loop(seed_messages)
        return self._store_outcome(context_id, task, outcome)

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    def list_pending(self) -> list[dict[str, Any]]:
        """Solo lectura, para el gestor de agentes — nunca expone credenciales."""
        return [
            {
                "context_id": context_id,
                "agent_id": "remote_ops",
                "kind": pending.kind,
                "summary": (
                    f"Diagnostico SSH pendiente de confirmar: {pending.device_name}"
                    if pending.kind == "run_diagnostic"
                    else pending.task
                ),
            }
            for context_id, pending in self._pending.items()
        ]

    def pending_kind(self, context_id: str) -> str | None:
        pending = self._pending.get(context_id)
        return pending.kind if pending else None

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)

    async def _run_diagnostic_and_record(self, pending: PendingRemoteOp) -> dict[str, Any]:
        if self._access is None:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El acceso a dispositivos no esta disponible."}

        try:
            conn = await self._access.get_connection(pending.device_id)
        except KeyError:
            return {"task": pending.task, "is_done": False, "content": None, "error": f"Ya no encuentro '{pending.device_name}' en el CMDB."}
        except PermissionError:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El Vault esta bloqueado — desbloquealo desde la pestana Vault e intenta de nuevo."}
        except RuntimeError as exc:
            return {"task": pending.task, "is_done": False, "content": None, "error": str(exc)}
        except ValueError as exc:
            return {"task": pending.task, "is_done": False, "content": None, "error": str(exc)}
        except Exception as exc:
            logger.exception("Fallo conectando a %s", pending.device_id)
            return {"task": pending.task, "is_done": False, "content": None, "error": f"No se pudo conectar a '{pending.device_name}': {exc}"}

        raw_sections: list[str] = []
        try:
            async with conn:
                for cmd, label in _DIAGNOSTIC_COMMANDS:
                    try:
                        result = await conn.run(cmd, timeout=30)
                        raw_sections.append(f"### {label}\n```\n{result.output}\n```")
                    except Exception as exc:
                        raw_sections.append(f"### {label}\n[error: {exc}]")
        except Exception as exc:
            logger.exception("Fallo durante el diagnostico de %s", pending.device_id)
            return {"task": pending.task, "is_done": False, "content": None, "error": f"El diagnostico se interrumpio: {exc}"}

        raw_output = "\n\n".join(raw_sections) if raw_sections else "Sin output de los comandos."

        content = raw_output
        if self._llm_router is not None:
            try:
                from agents.generation_agent import GenerationAgent

                prompt = (
                    f"Eres un experto en administracion de sistemas Linux. "
                    f"El usuario pregunto por el estado de '{pending.device_name}'.\n\n"
                    f"Analiza este output de diagnostico real y responde de forma clara y "
                    f"concisa. Si hay problemas, indicalos y sugiere acciones correctivas. "
                    f"No inventes nada que no este en el output.\n\n"
                    f"--- OUTPUT ---\n{raw_output}\n--- FIN ---"
                )
                summary = await GenerationAgent(self._llm_router).generate_response(prompt, "system", [])
                if summary:
                    content = summary
            except Exception:
                logger.exception("Fallo resumiendo el diagnostico con LLM — se devuelve el output crudo")

        from utils.logger import hito
        hito(
            "pepo.remote_ops | dispositivo=\"{dispositivo}\" | resultado=OK",
            dispositivo=pending.device_name,
        )
        return {"task": pending.task, "is_done": True, "content": content, "error": None}

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any] | None:
        """Continua/ejecuta lo pendiente. `user_reply` es obligatorio si el pendiente es 'ask_user'."""
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return None

        if pending.kind == "run_diagnostic":
            return await self._run_diagnostic_and_record(pending)

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
            if stored["kind"] == "run_diagnostic":
                return {
                    "task": pending.task, "is_done": False, "content": None, "error": None,
                    "next_device_id": stored["device_id"], "next_device_name": stored["device_name"],
                }

        return None
