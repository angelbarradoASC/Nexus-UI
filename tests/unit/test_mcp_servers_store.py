"""tests/unit/test_mcp_servers_store.py

Tests unitarios para DesktopMCPServerStore — persistencia SQLite de
definiciones de servidores MCP (mismo patron que
DesktopMonitoringIntegrationStore).
"""

from __future__ import annotations

import pytest

from desktop.storage.mcp_servers import DesktopMCPServer, DesktopMCPServerStore


def _store(tmp_path) -> DesktopMCPServerStore:
    return DesktopMCPServerStore(tmp_path / "mcp_servers.db")


def test_create_stdio_requires_command():
    with pytest.raises(ValueError):
        DesktopMCPServer.create(name="fs", transport="stdio")


def test_create_http_requires_url():
    with pytest.raises(ValueError):
        DesktopMCPServer.create(name="remoto", transport="http")


def test_create_rejects_unknown_transport():
    with pytest.raises(ValueError):
        DesktopMCPServer.create(name="raro", transport="websocket", command="x")


def test_create_requires_name():
    with pytest.raises(ValueError):
        DesktopMCPServer.create(name="", transport="stdio", command="python")


def test_save_and_get_by_name_roundtrip(tmp_path):
    store = _store(tmp_path)
    server = DesktopMCPServer.create(
        name="fs", transport="stdio", command="python", args=["server.py"],
    )
    store.save_server(server)

    fetched = store.get_by_name("fs")

    assert fetched is not None
    assert fetched.transport == "stdio"
    assert fetched.command == "python"
    assert fetched.args == ["server.py"]


def test_save_and_get_by_id_roundtrip(tmp_path):
    store = _store(tmp_path)
    server = DesktopMCPServer.create(name="remoto", transport="http", url="https://mcp.example.com")
    saved = store.save_server(server)

    fetched = store.get_server(saved.server_id)

    assert fetched is not None
    assert fetched.url == "https://mcp.example.com"


def test_list_servers_orders_by_name(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="zeta", transport="stdio", command="python"))
    store.save_server(DesktopMCPServer.create(name="alpha", transport="stdio", command="python"))

    names = [s.name for s in store.list_servers()]

    assert names == ["alpha", "zeta"]


def test_list_servers_enabled_only_filters_disabled(tmp_path):
    store = _store(tmp_path)
    store.save_server(DesktopMCPServer.create(name="activo", transport="stdio", command="python"))
    store.save_server(DesktopMCPServer.create(name="inactivo", transport="stdio", command="python", enabled=False))

    names = [s.name for s in store.list_servers(enabled_only=True)]

    assert names == ["activo"]


def test_save_upserts_by_server_id(tmp_path):
    store = _store(tmp_path)
    server = DesktopMCPServer.create(name="fs", transport="stdio", command="python")
    saved = store.save_server(server)

    saved.enabled = False
    store.save_server(saved)

    assert len(store.list_servers()) == 1
    assert store.get_by_name("fs").enabled is False


def test_delete_server(tmp_path):
    store = _store(tmp_path)
    saved = store.save_server(DesktopMCPServer.create(name="fs", transport="stdio", command="python"))

    deleted = store.delete_server(saved.server_id)

    assert deleted is True
    assert store.get_by_name("fs") is None


def test_delete_missing_server_returns_false(tmp_path):
    store = _store(tmp_path)

    assert store.delete_server("no-existe") is False


def test_get_by_name_missing_returns_none(tmp_path):
    store = _store(tmp_path)

    assert store.get_by_name("no-existe") is None
