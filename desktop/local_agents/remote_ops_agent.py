"""
desktop/local_agents/remote_ops_agent.py
--------------------------------------------
RemoteOpsAgent — hermano de SystemTaskAgent para infraestructura REMOTA
(servidores, no el PC local donde corre Nexus Desktop). Sobre
ConfirmableAgent (confirmable_loop.py) — el bucle de tool-calling, la
gestion de pendientes y la heuristica de ask_user_secret son compartidos
con SelfConfigAgent; aqui solo viven las tools propias y que hacer con
ellas.

- lookup_cmdb: busca el dispositivo por nombre/ip/tipo en el CMDB real.
  Solo lectura, se ejecuta sin confirmar.
- check_credentials: comprueba si hay credenciales en el Vault para ese
  device_id (bloqueado / ausentes / presentes) SIN revelar el secreto.
  Solo lectura, se ejecuta sin confirmar.
- run_diagnostic: propone conectarse por SSH y ejecutar un whitelist fijo
  de comandos de solo lectura. Pendiente de confirmacion humana antes de
  abrir la conexion. Usa AgentAccessService (CMDB + Vault + SSHConnector
  ya resueltos) — nunca las credenciales viejas de CredentialStore.

Solo soporta management_protocol == "ssh" (lo unico que AgentAccessService
implementa hoy). Para otros protocolos responde con honestidad que no esta
soportado todavia — no se inventa una integracion que no existe.
"""

from __future__ import annotations

import logging
from typing import Any

from desktop.local_agents.confirmable_loop import ConfirmableAgent, PendingAction, ProposalOutcome

logger = logging.getLogger("nexus.remote_ops_agent")

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
]


class RemoteOpsAgent(ConfirmableAgent):
    """Resuelve preguntas sobre infraestructura remota via CMDB + Vault + SSH real."""

    tools = _TOOLS
    prompt_key = "pepo.remote_ops_loop"
    agent_id = "remote_ops"

    def __init__(self, cfg, *, llm_router=None, cmdb=None, vault=None, access=None) -> None:
        super().__init__(cfg, llm_router=llm_router)
        self._cmdb = cmdb
        self._vault = vault
        self._access = access

    # ── Tools propias ────────────────────────────────────────────────────────

    async def dispatch_tool(self, name: str, args: dict[str, Any]) -> str | ProposalOutcome | None:
        if name == "lookup_cmdb":
            return await self._lookup_cmdb(args.get("query", ""))
        if name == "check_credentials":
            return await self._check_credentials(args.get("device_id", ""))
        if name == "run_diagnostic":
            return ProposalOutcome(
                kind="run_diagnostic",
                payload={
                    "device_id": args.get("device_id", ""),
                    "device_name": args.get("device_name") or args.get("device_id", ""),
                },
            )
        return None

    async def _lookup_cmdb(self, query: str) -> str:
        from nexus.cmdb.lookup import search_devices

        try:
            return await search_devices(self._cmdb, query)
        except Exception:
            logger.exception("Fallo consultando CMDB")
            return "Error consultando el CMDB."

    async def _check_credentials(self, device_id: str) -> str:
        from nexus.vault.check import check_credentials

        return await check_credentials(self._vault, device_id)

    # ── list_pending: resumen con nombre de dispositivo ─────────────────────

    def describe_pending(self, pending: PendingAction) -> str:
        if pending.kind == "run_diagnostic":
            return f"Diagnostico SSH pendiente de confirmar: {pending.payload.get('device_name')}"
        return pending.task

    # ── Ejecucion tras confirmar ─────────────────────────────────────────────

    async def execute(self, pending: PendingAction) -> dict[str, Any]:
        if pending.kind == "run_diagnostic":
            return await self._run_diagnostic_and_record(pending)
        return {"task": pending.task, "is_done": False, "content": None, "error": f"Pendiente desconocido: {pending.kind}"}

    async def _run_diagnostic_and_record(self, pending: PendingAction) -> dict[str, Any]:
        device_id = pending.payload.get("device_id", "")
        device_name = pending.payload.get("device_name", device_id)

        if self._access is None:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El acceso a dispositivos no esta disponible."}

        try:
            conn = await self._access.get_connection(device_id)
        except KeyError:
            return {"task": pending.task, "is_done": False, "content": None, "error": f"Ya no encuentro '{device_name}' en el CMDB."}
        except PermissionError:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El Vault esta bloqueado — desbloquealo desde la pestana Vault e intenta de nuevo."}
        except RuntimeError as exc:
            return {"task": pending.task, "is_done": False, "content": None, "error": str(exc)}
        except ValueError as exc:
            return {"task": pending.task, "is_done": False, "content": None, "error": str(exc)}
        except Exception as exc:
            logger.exception("Fallo conectando a %s", device_id)
            return {"task": pending.task, "is_done": False, "content": None, "error": f"No se pudo conectar a '{device_name}': {exc}"}

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
            logger.exception("Fallo durante el diagnostico de %s", device_id)
            return {"task": pending.task, "is_done": False, "content": None, "error": f"El diagnostico se interrumpio: {exc}"}

        raw_output = "\n\n".join(raw_sections) if raw_sections else "Sin output de los comandos."

        content = raw_output
        if self._llm_router is not None:
            try:
                from agents.generation_agent import GenerationAgent

                prompt = (
                    f"Eres un experto en administracion de sistemas Linux. "
                    f"El usuario pregunto por el estado de '{device_name}'.\n\n"
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
            dispositivo=device_name,
        )
        return {"task": pending.task, "is_done": True, "content": content, "error": None}
