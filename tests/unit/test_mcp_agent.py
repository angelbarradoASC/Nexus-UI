"""tests/unit/test_mcp_agent.py

Tests unitarios para MCPAgent — conectar servidores MCP por chat
(propose/confirm) y usar las tools de un servidor ya conectado, con
confirmacion humana para las tools "de escritura".
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.mcp_agent import MCPAgent
from desktop.storage.mcp_servers import DesktopMCPServer, DesktopMCPServerStore


class _FakeLLMResponse:
    def __init__(self, *, tool_calls=None, content=None, error=None):
        self.tool_calls = tool_calls
        self.content = content
        self.error = error


def _tool_call(call_id: str, tool_name: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": tool_name, "arguments": json.dumps(arguments)}}


class _FakeLLMRouter:
    def __init__(self, responses: list[_FakeLLMResponse]):
        self._responses = list(responses)

    async def call(self, **kwargs):
        return self._responses.pop(0)


class _FakeMCPManager:
    def __init__(self, *, tool_schemas=None, tools_error=None, call_results=None):
        self._tool_schemas = tool_schemas or []
        self._tools_error = tools_error
        self._call_results = call_results or {}
        self.calls: list[tuple] = []

    async def tools(self, server_def):
        if self._tools_error is not None:
            raise self._tools_error
        return list(self._tool_schemas)

    async def call(self, server_name, tool, arguments):
        self.calls.append((server_name, tool, arguments))
        return self._call_results.get(tool, f"resultado de {tool}")


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}}


def _store(tmp_path) -> DesktopMCPServerStore:
    return DesktopMCPServerStore(tmp_path / "mcp_servers.db")


def _fake_cfg() -> SimpleNamespace:
    return SimpleNamespace()


# ── Conectar un servidor nuevo ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_connect_server_creates_pending(tmp_path):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_connect_server",
            name="fs", transport="stdio", command="python", args=["server.py"],
        )]),
    ])
    manager = _FakeMCPManager()
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=_store(tmp_path))

    result = await agent.propose("ctx-1", "conecta un servidor MCP llamado fs")

    assert result["kind"] == "connect_server"
    assert result["payload"]["name"] == "fs"
    assert agent.has_pending("ctx-1") is True


@pytest.mark.asyncio
async def test_confirm_connect_server_persists_when_connection_succeeds(tmp_path):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_connect_server",
            name="fs", transport="stdio", command="python", args=["server.py"],
        )]),
    ])
    store = _store(tmp_path)
    manager = _FakeMCPManager(tool_schemas=[_schema("list_files"), _schema("read_file")])
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=store)
    await agent.propose("ctx-1", "conecta un servidor MCP llamado fs")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is True
    assert result["error"] is None
    assert "list_files" in result["content"]
    saved = store.get_by_name("fs")
    assert saved is not None
    assert saved.command == "python"


@pytest.mark.asyncio
async def test_confirm_connect_server_does_not_persist_when_connection_fails(tmp_path):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_connect_server",
            name="fs", transport="stdio", command="python-que-no-existe",
        )]),
    ])
    store = _store(tmp_path)
    manager = _FakeMCPManager(tools_error=RuntimeError("no se pudo lanzar el proceso"))
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=store)
    await agent.propose("ctx-1", "conecta un servidor MCP llamado fs")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is False
    assert result["error"]
    assert store.get_by_name("fs") is None


@pytest.mark.asyncio
async def test_list_connected_servers_reports_saved_servers(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="fs", transport="stdio", command="python"))
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "list_connected_servers")]),
        _FakeLLMResponse(tool_calls=[_tool_call("c2", "finish", summary="Solo hay 'fs' conectado.")]),
    ])
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=_FakeMCPManager(), server_store=store)

    result = await agent.propose("ctx-1", "que servidores mcp tengo")

    assert result["kind"] == "finish"
    assert "fs" in result["summary"]


# ── Usar un servidor ya conectado ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_use_server_loads_dynamic_tools_from_manager(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="fs", transport="stdio", command="python"))
    manager = _FakeMCPManager(tool_schemas=[_schema("list_files")])
    agent = MCPAgent(_fake_cfg(), llm_router=_FakeLLMRouter([]), manager=manager, server_store=store)

    ok = await agent.use_server("fs")

    assert ok is True
    assert agent.tools == [_schema("list_files")]
    assert agent.prompt_key == "pepo.mcp_use_loop"
    assert agent.agent_id == "mcp.fs"


@pytest.mark.asyncio
async def test_use_server_returns_false_for_unknown_server(tmp_path):
    agent = MCPAgent(_fake_cfg(), llm_router=_FakeLLMRouter([]), manager=_FakeMCPManager(), server_store=_store(tmp_path))

    assert await agent.use_server("no-existe") is False


@pytest.mark.asyncio
async def test_read_only_tool_executes_directly_without_confirmation(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="fs", transport="stdio", command="python"))
    manager = _FakeMCPManager(
        tool_schemas=[_schema("list_files")],
        call_results={"list_files": "a.txt, b.txt"},
    )
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "list_files")]),
        _FakeLLMResponse(tool_calls=[_tool_call("c2", "finish", summary="Hay a.txt y b.txt.")]),
    ])
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=store)
    await agent.use_server("fs")

    result = await agent.propose("ctx-1", "lista los ficheros")

    assert result["kind"] == "finish"
    assert manager.calls == [("fs", "list_files", {})]
    assert agent.has_pending("ctx-1") is False


@pytest.mark.asyncio
async def test_write_tool_requires_confirmation_before_executing(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="notion", transport="stdio", command="python"))
    manager = _FakeMCPManager(
        tool_schemas=[_schema("create_page")],
        call_results={"create_page": "pagina creada: p-123"},
    )
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "create_page", title="Onboarding")]),
    ])
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=store)
    await agent.use_server("notion")

    proposal = await agent.propose("ctx-1", "crea una pagina de onboarding en notion")

    assert proposal["kind"] == "mcp_call"
    assert proposal["payload"]["tool"] == "create_page"
    assert manager.calls == []  # nada ejecutado todavia

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is True
    assert result["content"] == "pagina creada: p-123"
    assert manager.calls == [("notion", "create_page", {"title": "Onboarding"})]


@pytest.mark.asyncio
async def test_cancel_write_tool_call_does_not_execute(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="notion", transport="stdio", command="python"))
    manager = _FakeMCPManager(tool_schemas=[_schema("delete_page")])
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "delete_page", page_id="p-1")]),
    ])
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=store)
    await agent.use_server("notion")
    await agent.propose("ctx-1", "borra la pagina p-1")

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert manager.calls == []
