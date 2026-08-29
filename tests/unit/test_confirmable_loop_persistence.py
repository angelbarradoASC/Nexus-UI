"""tests/unit/test_confirmable_loop_persistence.py

Tests de persistencia para ConfirmableAgent — el estado pendiente debe
sobrevivir un reinicio del proceso via DesktopPendingActionStore, para las
3 subclases (RemoteOpsAgent, SelfConfigAgent, MCPAgent), cada una con su
propia `persistence_key` fija (MCPAgent muta `agent_id` en tiempo real
segun el servidor activo — `persistence_key` NO debe seguirlo).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.mcp_agent import MCPAgent
from desktop.local_agents.remote_ops_agent import RemoteOpsAgent
from desktop.local_agents.self_config_agent import SelfConfigAgent
from desktop.storage.pending_actions import DesktopPendingActionStore


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


class _FakeCMDB:
    async def list_devices(self, enabled_only: bool = True):
        return []

    async def create(self, device):
        return device


class _FakeMCPManager:
    def __init__(self, tool_schemas=None):
        self._tool_schemas = tool_schemas or []

    async def tools(self, server_def):
        return list(self._tool_schemas)

    async def call(self, server_name, tool, arguments):
        return "ok"


def _store(tmp_path) -> DesktopPendingActionStore:
    return DesktopPendingActionStore(tmp_path / "pending_actions.db")


def _fake_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        assets_crm_enabled=False, assets_crm_base_url="", assets_crm_username="", assets_crm_password="",
        crm_odoo_enabled=False, crm_odoo_base_url="", crm_odoo_database="", crm_odoo_username="",
        crm_odoo_password="", crm_odoo_default_team="", crm_odoo_default_stage="",
    )


@pytest.mark.asyncio
async def test_remote_ops_agent_persists_run_diagnostic_pending(tmp_path):
    store = _store(tmp_path)
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "run_diagnostic", device_id="dev-1", device_name="BeaServer")]),
    ])
    agent = RemoteOpsAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=None, access=None, store=store)

    await agent.propose("ctx-1", "revisa BeaServer")

    rows = store.list_for_agent("remote_ops")
    assert len(rows) == 1
    assert rows[0].kind == "run_diagnostic"
    assert rows[0].payload["device_name"] == "BeaServer"


@pytest.mark.asyncio
async def test_remote_ops_agent_rehydrates_after_restart(tmp_path):
    store = _store(tmp_path)
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "run_diagnostic", device_id="dev-1", device_name="BeaServer")]),
    ])
    first_agent = RemoteOpsAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=None, access=None, store=store)
    await first_agent.propose("ctx-1", "revisa BeaServer")

    second_agent = RemoteOpsAgent(_fake_cfg(), llm_router=None, cmdb=None, vault=None, access=None, store=store)
    second_agent.load_pending_from_store()

    assert second_agent.has_pending("ctx-1") is True
    assert second_agent.pending_kind("ctx-1") == "run_diagnostic"


@pytest.mark.asyncio
async def test_self_config_agent_confirm_forgets_from_store(tmp_path):
    store = _store(tmp_path)
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_set_crm_config", provider="odoo", base_url="https://odoo.local",
            username="admin", secret="pw",
        )]),
    ])
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=None, local_state=None, store=store)
    await agent.propose("ctx-1", "conecta a Odoo")
    assert store.list_for_agent("self_config") != []

    await agent.confirm("ctx-1")

    assert store.list_for_agent("self_config") == []


@pytest.mark.asyncio
async def test_mcp_agent_persistence_key_is_fixed_across_modes(tmp_path):
    """persistence_key ("mcp") NO debe seguir a agent_id (que muta a
    "mcp.<servidor>" en modo usar) — si lo hiciera, load_pending_from_store()
    tras un reinicio no encontraria los pendientes guardados en modo usar."""
    store = _store(tmp_path)
    manager = _FakeMCPManager(tool_schemas=[{
        "type": "function",
        "function": {"name": "create_page", "description": "", "parameters": {"type": "object", "properties": {}}},
    }])
    from desktop.storage.mcp_servers import DesktopMCPServer, DesktopMCPServerStore

    server_store = DesktopMCPServerStore(tmp_path / "mcp_servers.db")
    server_store.save_server(DesktopMCPServer.create(name="notion", transport="stdio", command="python"))

    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "create_page", title="Onboarding")]),
    ])
    agent = MCPAgent(_fake_cfg(), llm_router=llm, manager=manager, server_store=server_store, store=store)
    await agent.use_server("notion")
    assert agent.agent_id == "mcp.notion"

    await agent.propose("ctx-1", "crea una pagina")

    rows = store.list_for_agent("mcp")
    assert len(rows) == 1
    assert rows[0].payload["server_name"] == "notion"

    second_agent = MCPAgent(_fake_cfg(), llm_router=None, manager=manager, server_store=server_store, store=store)
    second_agent.load_pending_from_store()

    assert second_agent.has_pending("ctx-1") is True
