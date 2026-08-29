"""tests/unit/test_remote_ops_agent.py

Tests de regresion para RemoteOpsAgent — escritos ANTES de refactorizarlo
para heredar de ConfirmableAgent (Fase 2 del plan de mejoras inspiradas en
OpenWorker). Deben pasar igual antes y despues del refactor: mismo
comportamiento externo, solo cambia donde vive el bucle.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.remote_ops_agent import RemoteOpsAgent


class _FakeLLMResponse:
    def __init__(self, *, tool_calls=None, content=None, error=None):
        self.tool_calls = tool_calls
        self.content = content
        self.error = error


def _tool_call(call_id: str, name: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


class _FakeLLMRouter:
    def __init__(self, responses: list[_FakeLLMResponse]):
        self._responses = list(responses)

    async def call(self, **kwargs):
        return self._responses.pop(0)


class _FakeCMDB:
    def __init__(self, devices: list | None = None):
        self._devices = devices or []

    async def list_devices(self, enabled_only: bool = True):
        return list(self._devices)


class _FakeVault:
    def __init__(self, *, is_locked: bool = False, credential=None):
        self.is_locked = is_locked
        self._credential = credential

    async def get_credential(self, device_id):
        return self._credential


class _FakeConnection:
    def __init__(self, outputs: dict[str, str] | None = None):
        self._outputs = outputs or {}
        self.ran_commands: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, cmd, timeout=30):
        self.ran_commands.append(cmd)
        return SimpleNamespace(output=self._outputs.get(cmd, f"output de {cmd}"))


class _FakeAccessService:
    def __init__(self, *, connection=None, raise_error: Exception | None = None):
        self._connection = connection
        self._raise_error = raise_error
        self.requested_device_ids: list[str] = []

    async def get_connection(self, device_id):
        self.requested_device_ids.append(device_id)
        if self._raise_error is not None:
            raise self._raise_error
        return self._connection


class _Device:
    def __init__(self, device_id, name, ip="10.0.0.5", type="server", management_protocol="ssh", vendor="", notes="", fqdn=None, tags=None):
        self.device_id = device_id
        self.name = name
        self.ip = ip
        self.type = type
        self.management_protocol = management_protocol
        self.vendor = vendor
        self.notes = notes
        self.fqdn = fqdn
        self.tags = tags or {}


# ── lookup_cmdb / check_credentials (solo lectura) ─────────────────────────

@pytest.mark.asyncio
async def test_lookup_cmdb_then_check_credentials_then_finish():
    device = _Device("dev-bea", "BeaServer")
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "lookup_cmdb", query="BeaServer")]),
        _FakeLLMResponse(tool_calls=[_tool_call("c2", "check_credentials", device_id="dev-bea")]),
        _FakeLLMResponse(tool_calls=[_tool_call("c3", "finish", summary="BeaServer tiene credenciales listas.")]),
    ])
    agent = RemoteOpsAgent(
        None, llm_router=llm, cmdb=_FakeCMDB([device]),
        vault=_FakeVault(credential=SimpleNamespace(username="admin", auth_method="password")),
        access=None,
    )

    result = await agent.propose("ctx-1", "que tal esta BeaServer")

    assert result["kind"] == "finish"
    assert "credenciales" in result["summary"].lower()
    assert agent.has_pending("ctx-1") is False


# ── run_diagnostic: propone y queda pendiente de confirmar ─────────────────

@pytest.mark.asyncio
async def test_run_diagnostic_proposal_creates_pending():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "lookup_cmdb", query="BeaServer")]),
        _FakeLLMResponse(tool_calls=[_tool_call("c2", "run_diagnostic", device_id="dev-bea", device_name="BeaServer")]),
    ])
    agent = RemoteOpsAgent(None, llm_router=llm, cmdb=_FakeCMDB([_Device("dev-bea", "BeaServer")]), vault=_FakeVault(), access=None)

    result = await agent.propose("ctx-1", "revisa BeaServer")

    assert result["kind"] == "run_diagnostic"
    assert result["payload"]["device_id"] == "dev-bea"
    assert result["payload"]["device_name"] == "BeaServer"
    assert agent.has_pending("ctx-1") is True
    assert agent.pending_kind("ctx-1") == "run_diagnostic"


@pytest.mark.asyncio
async def test_confirm_run_diagnostic_executes_ssh_commands_and_returns_content():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "run_diagnostic", device_id="dev-bea", device_name="BeaServer")]),
    ])
    conn = _FakeConnection()
    access = _FakeAccessService(connection=conn)
    agent = RemoteOpsAgent(None, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), access=access)
    await agent.propose("ctx-1", "revisa BeaServer")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is True
    assert result["error"] is None
    assert access.requested_device_ids == ["dev-bea"]
    assert len(conn.ran_commands) == 5  # uptime, free, df, ps, journalctl/tail
    assert agent.has_pending("ctx-1") is False


@pytest.mark.asyncio
async def test_confirm_run_diagnostic_reports_locked_vault():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "run_diagnostic", device_id="dev-bea", device_name="BeaServer")]),
    ])
    access = _FakeAccessService(raise_error=PermissionError())
    agent = RemoteOpsAgent(None, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), access=access)
    await agent.propose("ctx-1", "revisa BeaServer")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is False
    assert "bloqueado" in result["error"].lower()


# ── ask_user: pregunta y continua tras la respuesta ─────────────────────────

@pytest.mark.asyncio
async def test_ask_user_roundtrip_then_proposes_run_diagnostic():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "ask_user", question="¿Cual de los dos servidores, el de produccion o el de test?")]),
        _FakeLLMResponse(tool_calls=[_tool_call("c2", "run_diagnostic", device_id="dev-prod", device_name="Prod-01")]),
    ])
    agent = RemoteOpsAgent(None, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), access=None)

    proposal = await agent.propose("ctx-1", "revisa el servidor")
    assert proposal["kind"] == "ask_user"
    assert agent.has_pending("ctx-1") is True

    result = await agent.confirm("ctx-1", "el de produccion")

    assert result["next_kind"] == "run_diagnostic"
    assert result["next_payload"]["device_id"] == "dev-prod"
    assert result["next_payload"]["device_name"] == "Prod-01"
    assert agent.pending_kind("ctx-1") == "run_diagnostic"


# ── cancel ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_clears_pending_without_connecting():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "run_diagnostic", device_id="dev-bea", device_name="BeaServer")]),
    ])
    access = _FakeAccessService(connection=_FakeConnection())
    agent = RemoteOpsAgent(None, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), access=access)
    await agent.propose("ctx-1", "revisa BeaServer")

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert access.requested_device_ids == []


# ── list_pending: forma para el gestor de agentes ───────────────────────────

@pytest.mark.asyncio
async def test_list_pending_describes_run_diagnostic_with_device_name():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "run_diagnostic", device_id="dev-bea", device_name="BeaServer")]),
    ])
    agent = RemoteOpsAgent(None, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), access=None)
    await agent.propose("ctx-1", "revisa BeaServer")

    pending = await agent.list_pending()

    assert len(pending) == 1
    assert pending[0]["agent_id"] == "remote_ops"
    assert pending[0]["kind"] == "run_diagnostic"
    assert "BeaServer" in pending[0]["summary"]
