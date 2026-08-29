"""tests/unit/test_pending_actions_store.py

Tests unitarios para DesktopPendingActionStore — persistencia SQLite del
estado pendiente de confirmar de los 5 agentes locales de PEPO (Mouse,
SystemTask, RemoteOps, SelfConfig, MCP), para que sobreviva un reinicio
del proceso.
"""

from __future__ import annotations

from desktop.storage.pending_actions import DesktopPendingActionStore


def _store(tmp_path) -> DesktopPendingActionStore:
    return DesktopPendingActionStore(tmp_path / "pending_actions.db")


def test_save_and_list_roundtrip(tmp_path):
    store = _store(tmp_path)

    store.save(
        agent_id="self_config", context_id="ctx-1", kind="store_credential",
        task="añade BeaServer", payload={"device_name": "BeaServer", "username": "admin"},
        messages=[{"role": "user", "content": "hola"}], tool_call_id="call-1",
    )

    rows = store.list_for_agent("self_config")

    assert len(rows) == 1
    assert rows[0].context_id == "ctx-1"
    assert rows[0].kind == "store_credential"
    assert rows[0].payload == {"device_name": "BeaServer", "username": "admin"}
    assert rows[0].messages == [{"role": "user", "content": "hola"}]
    assert rows[0].tool_call_id == "call-1"


def test_list_for_agent_only_returns_matching_agent(tmp_path):
    store = _store(tmp_path)
    store.save(agent_id="mcp", context_id="ctx-1", kind="mcp_call")
    store.save(agent_id="mouse", context_id="ctx-1", kind="mouse_speed")

    mcp_rows = store.list_for_agent("mcp")

    assert len(mcp_rows) == 1
    assert mcp_rows[0].agent_id == "mcp"


def test_save_upserts_by_agent_and_context(tmp_path):
    store = _store(tmp_path)
    store.save(agent_id="remote_ops", context_id="ctx-1", kind="ask_user", task="v1")

    store.save(agent_id="remote_ops", context_id="ctx-1", kind="run_diagnostic", task="v2")

    rows = store.list_for_agent("remote_ops")
    assert len(rows) == 1
    assert rows[0].kind == "run_diagnostic"
    assert rows[0].task == "v2"


def test_delete_removes_only_that_row(tmp_path):
    store = _store(tmp_path)
    store.save(agent_id="mouse", context_id="ctx-1", kind="mouse_speed")
    store.save(agent_id="mouse", context_id="ctx-2", kind="mouse_speed")

    store.delete(agent_id="mouse", context_id="ctx-1")

    rows = store.list_for_agent("mouse")
    assert len(rows) == 1
    assert rows[0].context_id == "ctx-2"


def test_delete_missing_row_is_a_noop(tmp_path):
    store = _store(tmp_path)

    store.delete(agent_id="mouse", context_id="no-existe")

    assert store.list_for_agent("mouse") == []


def test_list_for_agent_empty_by_default(tmp_path):
    store = _store(tmp_path)

    assert store.list_for_agent("self_config") == []


def test_defaults_for_optional_fields(tmp_path):
    store = _store(tmp_path)

    store.save(agent_id="system_task", context_id="ctx-1", kind="windows_use")

    row = store.list_for_agent("system_task")[0]
    assert row.task == ""
    assert row.payload == {}
    assert row.messages == []
    assert row.tool_call_id is None
