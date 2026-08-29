"""tests/integration/test_mcp_manager_live.py

Verificacion end-to-end de MCPManager con un servidor MCP real (no un
mock) — lanza tests/integration/fixtures/mcp_echo_server.py como
subproceso stdio via el SDK oficial `mcp` (mismo mecanismo que usara
MCPAgent con un servidor MCP de verdad) y comprueba list_tools + call_tool
sobre la conexion real.

Confirma en CI/local que la version anclada de `mcp` (ver
desktop/requirements.txt) sigue siendo funcional, no solo importable.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from nexus.mcp.manager import MCPManager, MCPServerDef

_FIXTURE = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"


@pytest.fixture(scope="module")
def event_loop_policy():
    # pytest-asyncio, en Windows, no siempre usa la policy por defecto
    # (WindowsProactorEventLoopPolicy) que asyncio.run() sí usa — con
    # SelectorEventLoop, crear un subproceso falla con NotImplementedError.
    # El SDK mcp necesita subprocesos reales (stdio) para conectar. Sin
    # esto, este test fallaba SOLO bajo pytest, no en uso normal.
    if sys.platform == "win32":
        return asyncio.WindowsProactorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


def _server_def() -> MCPServerDef:
    return MCPServerDef(name="echo-live", transport="stdio", command=sys.executable, args=[str(_FIXTURE)])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_manager_connects_lists_tools_and_calls_one():
    manager = MCPManager()
    try:
        schemas = await manager.tools(_server_def())
        names = {t["function"]["name"] for t in schemas}
        assert names == {"echo", "create_note"}

        result = await manager.call("echo-live", "echo", {"text": "hola mcp"})
        assert result == "echo: hola mcp"
    finally:
        await manager.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_manager_reuses_existing_connection():
    manager = MCPManager()
    try:
        await manager.tools(_server_def())
        assert manager.is_connected("echo-live") is True

        # Segunda llamada no debe abrir una segunda conexion — ensure() la reutiliza.
        conn_before = manager._conns["echo-live"]
        await manager.ensure(_server_def())
        assert manager._conns["echo-live"] is conn_before
    finally:
        await manager.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_manager_disconnect_allows_reconnect():
    manager = MCPManager()
    try:
        await manager.tools(_server_def())
        await manager.disconnect("echo-live")
        assert manager.is_connected("echo-live") is False

        with pytest.raises(RuntimeError):
            await manager.call("echo-live", "echo", {"text": "otra vez"})
    finally:
        await manager.aclose()
