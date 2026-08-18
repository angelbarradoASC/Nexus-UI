"""
desktop/local_agents/mcp_agent.py
--------------------------------------
MCPAgent — permite a PEPO (1) conectarse a un servidor MCP (Model Context
Protocol) nuevo por chat, con el mismo patron propose/confirm que Vault/CRM
(SelfConfigAgent), y (2) usar las tools de un servidor MCP YA conectado
dentro del mismo bucle de tool-calling compartido (ConfirmableAgent).

Dos modos del mismo agente, elegidos ANTES de llamar a propose():
- use_connect_mode() (por defecto): tools = _CONNECT_TOOLS, para dar de
  alta un servidor nuevo.
- await use_server(name): carga las tools REALES de un servidor ya
  guardado (via MCPManager.tools()) y las expone en el bucle — el LLM ve
  exactamente las tools que ese servidor MCP declara, no una lista fija.

Las tools "de escritura" de un servidor conectado (heuristica por prefijo
de nombre: send_/create_/delete_/write_/update_/remove_/post_/put_/patch_
— mismo criterio que ya usa PermissionLevel en skill_router.py para
distinguir ASSIST/OPERATE) se convierten en una ProposalOutcome pendiente
de confirmacion humana; las de solo lectura se ejecutan directo via
MCPManager.call().

Nota de alcance (v1, ver plan): secret_ref se guarda pero NO se usa aun
para autenticar transportes http — el v1 se probo con servidores MCP
simples sin OAuth (stdio). Cablear la auth es una extension futura, no
un olvido.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from desktop.local_agents.confirmable_loop import ConfirmableAgent, PendingAction, ProposalOutcome
from desktop.storage.mcp_servers import DesktopMCPServer

logger = logging.getLogger("nexus.mcp_agent")

_WRITE_TOOL_PATTERN = re.compile(
    r"^(send|create|delete|write|update|remove|post|put|patch|publish|execute|run|deploy)[_\-]",
    re.IGNORECASE,
)

_CONNECT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_connected_servers",
            "description": "Lista los servidores MCP ya conectados y guardados, con su transporte y numero de tools. Usalo antes de asumir que un servidor no esta conectado.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_connect_server",
            "description": (
                "Propone conectar un servidor MCP nuevo. Pendiente de confirmacion humana — "
                "NUNCA conecta nada todavia. Al confirmar, se intenta la conexion real de "
                "verdad (no solo se guarda) y solo se persiste si funciona."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre corto para identificar este servidor despues (por ejemplo 'notion', 'ficheros-proyecto')."},
                    "transport": {"type": "string", "description": "'stdio' (comando local) o 'http' (URL remota)."},
                    "command": {"type": "string", "description": "Solo si transport=stdio: el ejecutable a lanzar."},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "Solo si transport=stdio: argumentos del comando."},
                    "url": {"type": "string", "description": "Solo si transport=http: la URL del servidor MCP."},
                    "secret_ref": {"type": "string", "description": "Referencia a un secreto (token/API key) ya obtenido via ask_user_secret, si el servidor lo requiere."},
                },
                "required": ["name", "transport"],
            },
        },
    },
]


class MCPAgent(ConfirmableAgent):
    """Conecta servidores MCP y usa sus tools — ver docstring del modulo."""

    tools = _CONNECT_TOOLS
    prompt_key = "pepo.mcp_connect_loop"
    agent_id = "mcp"

    def __init__(self, cfg, *, llm_router=None, manager=None, store=None) -> None:
        super().__init__(cfg, llm_router=llm_router)
        self._manager = manager
        self._store = store
        self._active_server_name: str | None = None

    # ── Cambio de modo (antes de propose()) ─────────────────────────────────

    def use_connect_mode(self) -> None:
        self.tools = _CONNECT_TOOLS
        self.prompt_key = "pepo.mcp_connect_loop"
        self.agent_id = "mcp"
        self._active_server_name = None

    async def use_server(self, server_name: str) -> bool:
        """Prepara el bucle para usar las tools REALES de un servidor MCP ya
        conectado. Devuelve False si el servidor no existe/esta deshabilitado
        o si la conexion falla — en ese caso el modo no cambia."""
        if self._store is None or self._manager is None:
            return False
        server = self._store.get_by_name(server_name)
        if server is None or not server.enabled:
            return False
        try:
            schemas = await self._manager.tools(_to_server_def(server))
        except Exception:
            logger.exception("Fallo listando tools del servidor MCP '%s'", server_name)
            return False
        self.tools = schemas
        self.prompt_key = "pepo.mcp_use_loop"
        self.agent_id = f"mcp.{server_name}"
        self._active_server_name = server_name
        return True

    # ── Tools ────────────────────────────────────────────────────────────────

    async def dispatch_tool(self, name: str, args: dict[str, Any]) -> str | ProposalOutcome | None:
        if self._active_server_name is None:
            if name == "list_connected_servers":
                return self._list_connected_servers_text()
            if name == "propose_connect_server":
                return ProposalOutcome(kind="connect_server", payload=args)
            return None

        if _WRITE_TOOL_PATTERN.match(name):
            return ProposalOutcome(
                kind="mcp_call",
                payload={"server_name": self._active_server_name, "tool": name, "arguments": args},
            )
        try:
            return await self._manager.call(self._active_server_name, name, args)
        except Exception as exc:
            logger.exception("Fallo ejecutando la tool MCP '%s' en '%s'", name, self._active_server_name)
            return f"Error ejecutando '{name}': {exc}"

    def _list_connected_servers_text(self) -> str:
        if self._store is None:
            return "No hay almacen de servidores MCP disponible."
        servers = self._store.list_servers()
        if not servers:
            return "No hay ningun servidor MCP conectado todavia."
        lines = [
            f"- {s.name} ({s.transport}, {'activo' if s.enabled else 'deshabilitado'})"
            for s in servers
        ]
        return "Servidores MCP conectados:\n" + "\n".join(lines)

    # ── Ejecucion tras confirmar ─────────────────────────────────────────────

    def describe_pending(self, pending: PendingAction) -> str:
        if pending.kind == "connect_server":
            return f"Conectar servidor MCP '{pending.payload.get('name', '?')}'"
        if pending.kind == "mcp_call":
            return f"{pending.payload.get('tool', '?')} en servidor MCP '{pending.payload.get('server_name', '?')}'"
        return pending.task

    async def execute(self, pending: PendingAction) -> dict[str, Any]:
        if pending.kind == "connect_server":
            return await self._execute_connect_server(pending)
        if pending.kind == "mcp_call":
            return await self._execute_mcp_call(pending)
        return {"task": pending.task, "is_done": False, "content": None, "error": f"Pendiente desconocido: {pending.kind}"}

    async def _execute_connect_server(self, pending: PendingAction) -> dict[str, Any]:
        payload = pending.payload
        try:
            server = DesktopMCPServer.create(
                name=payload.get("name", ""),
                transport=payload.get("transport", ""),
                command=payload.get("command", ""),
                args=payload.get("args") or [],
                url=payload.get("url", ""),
                secret_ref=payload.get("secret_ref", ""),
            )
        except ValueError as exc:
            return {"task": pending.task, "is_done": False, "content": None, "error": str(exc)}

        if self._manager is None:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El cliente MCP no esta disponible."}

        try:
            tool_schemas = await self._manager.tools(_to_server_def(server))
        except Exception as exc:
            logger.exception("Fallo conectando al servidor MCP '%s'", server.name)
            return {"task": pending.task, "is_done": False, "content": None, "error": f"No pude conectar: {exc}"}

        if self._store is not None:
            self._store.save_server(server)

        from utils.logger import hito
        hito(
            "pepo.mcp | conectar | servidor=\"{servidor}\" | tools={n_tools} | resultado=OK",
            servidor=server.name, n_tools=len(tool_schemas),
        )
        tool_names = ", ".join(t["function"]["name"] for t in tool_schemas) or "ninguna"
        return {
            "task": pending.task, "is_done": True,
            "content": f"Conectado a '{server.name}'. Tools disponibles: {tool_names}.",
            "error": None,
        }

    async def _execute_mcp_call(self, pending: PendingAction) -> dict[str, Any]:
        payload = pending.payload
        server_name = payload.get("server_name", "")
        tool = payload.get("tool", "")
        arguments = payload.get("arguments") or {}
        if self._manager is None:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El cliente MCP no esta disponible."}
        try:
            result = await self._manager.call(server_name, tool, arguments)
        except Exception as exc:
            logger.exception("Fallo ejecutando la tool MCP '%s' en '%s'", tool, server_name)
            return {"task": pending.task, "is_done": False, "content": None, "error": f"No pude ejecutar '{tool}': {exc}"}

        from utils.logger import hito
        hito(
            "pepo.mcp | ejecutar_tool | servidor=\"{servidor}\" | tool=\"{tool}\" | resultado=OK",
            servidor=server_name, tool=tool,
        )
        return {"task": pending.task, "is_done": True, "content": result, "error": None}


def _to_server_def(server: DesktopMCPServer):
    from nexus.mcp.manager import MCPServerDef

    return MCPServerDef(
        name=server.name,
        transport=server.transport,
        command=server.command,
        args=list(server.args),
        url=server.url,
        env={},
    )
