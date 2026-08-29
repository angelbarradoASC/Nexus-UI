"""
app/nexus/mcp/manager.py
---------------------------
MCPManager — cliente MCP (Model Context Protocol) propio para que PEPO se
conecte a servidores MCP externos (Slack, Notion, filesystem, lo que sea)
sin escribir una clase Python nueva por integracion. Patron inspirado en
como OpenWorker (andrewyng/openworker, coworker/mcp/client.py) organiza su
cliente MCP, pero escrito desde cero para las convenciones de este
proyecto — logging con logger estandar, sin dependencias de su framework.

Una tarea asyncio por servidor conectado, que abre el transporte + la
ClientSession del SDK oficial `mcp` y las mantiene vivas hasta que se pide
desconectar — necesario porque los transportes del SDK usan anyio cancel
scopes que deben entrar y salir en la MISMA tarea; llamar a las tools desde
otra tarea del mismo loop es seguro.

Ver desktop/requirements.txt para el conflicto de versiones real
descubierto al instalar `mcp` (starlette/pydantic) y por que esta anclado
a mcp==1.6.0.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.mcp.manager")


@dataclass(slots=True)
class MCPServerDef:
    """Definicion de un servidor MCP a conectar — ver desktop/storage/mcp_servers.py."""

    name: str
    transport: str  # "stdio" | "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)


class _Conn:
    def __init__(self, session: Any, tools: list[Any]) -> None:
        self.session = session
        self.tools = tools
        self.shutdown = asyncio.Event()


def mcp_tool_to_function_schema(tool: Any) -> dict[str, Any]:
    """Convierte un mcp.types.Tool al formato OpenAI function-calling que
    ya usa ConfirmableAgent — mismo `tools` que el resto de skills."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}},
        },
    }


def _result_text(result: Any) -> str:
    """Extrae el texto de un CallToolResult — el bucle de tool-calling de
    PEPO espera un string como resultado de cada tool."""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else str(result)


class MCPManager:
    """Owns conexiones MCP persistentes por nombre de servidor. Conecta
    perezosamente (la primera vez que se pide, no al arrancar la app)."""

    def __init__(self) -> None:
        self._conns: dict[str, _Conn] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def ensure(self, server: MCPServerDef) -> _Conn:
        async with self._lock:
            existing = self._conns.get(server.name)
            if existing is not None:
                return existing
            ready: asyncio.Future = asyncio.get_running_loop().create_future()
            self._tasks[server.name] = asyncio.create_task(self._serve(server, ready))
            conn = await ready  # propaga errores de conexion
            self._conns[server.name] = conn
            return conn

    async def tools(self, server: MCPServerDef) -> list[dict[str, Any]]:
        """Tools del servidor ya convertidas al formato function-calling."""
        conn = await self.ensure(server)
        return [mcp_tool_to_function_schema(tool) for tool in conn.tools]

    async def call(self, server_name: str, tool: str, arguments: dict[str, Any] | None) -> str:
        conn = self._conns.get(server_name)
        if conn is None:
            raise RuntimeError(f"Servidor MCP no conectado: {server_name}")
        result = await conn.session.call_tool(tool, arguments or {})
        return _result_text(result)

    def is_connected(self, server_name: str) -> bool:
        return server_name in self._conns

    async def disconnect(self, server_name: str) -> None:
        conn = self._conns.pop(server_name, None)
        if conn is None:
            return
        conn.shutdown.set()
        task = self._tasks.pop(server_name, None)
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except Exception:
                task.cancel()

    async def aclose(self) -> None:
        for name in list(self._conns.keys()):
            await self.disconnect(name)

    # ── ciclo de vida por servidor (una tarea entra y sale del stack) ────────

    async def _serve(self, server: MCPServerDef, ready: asyncio.Future) -> None:
        try:
            async with AsyncExitStack() as stack:
                if server.transport == "stdio":
                    if not server.command:
                        raise ValueError(f"Servidor MCP '{server.name}' es stdio pero no tiene 'command'")
                    from mcp import StdioServerParameters
                    from mcp.client.stdio import stdio_client

                    params = StdioServerParameters(command=server.command, args=server.args, env=server.env or None)
                    read, write = await stack.enter_async_context(stdio_client(params))
                elif server.transport == "http":
                    if not server.url:
                        raise ValueError(f"Servidor MCP '{server.name}' es http pero no tiene 'url'")
                    from mcp.client.streamable_http import streamablehttp_client

                    read, write, _ = await stack.enter_async_context(streamablehttp_client(server.url))
                else:
                    raise ValueError(f"Transporte MCP desconocido: {server.transport}")

                from mcp import ClientSession

                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools_result = await session.list_tools()
                conn = _Conn(session=session, tools=list(tools_result.tools))
                if not ready.done():
                    ready.set_result(conn)
                await conn.shutdown.wait()
        except Exception as exc:
            logger.exception("Fallo conectando al servidor MCP '%s'", server.name)
            if not ready.done():
                ready.set_exception(exc)
