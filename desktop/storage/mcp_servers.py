"""SQLite-backed MCP server definitions for Nexus Desktop.

Mismo patron que monitoring_integrations.py — nombre, transporte y datos
de conexion; ningun secreto en texto plano aqui (`secret_ref` apunta a una
entrada del Vault ya existente, igual que en las otras integraciones)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_servers (
    server_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    transport TEXT NOT NULL,
    command TEXT NOT NULL DEFAULT '',
    args_json TEXT NOT NULL DEFAULT '[]',
    url TEXT NOT NULL DEFAULT '',
    secret_ref TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'chat',
    updated_at TEXT NOT NULL
);
"""

_SUPPORTED_TRANSPORTS = ("stdio", "http")


@dataclass(slots=True)
class DesktopMCPServer:
    server_id: str
    name: str
    transport: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    secret_ref: str = ""
    enabled: bool = True
    source: str = "chat"
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        name: str,
        transport: str,
        command: str = "",
        args: list[str] | None = None,
        url: str = "",
        secret_ref: str = "",
        enabled: bool = True,
        source: str = "chat",
        server_id: str | None = None,
    ) -> "DesktopMCPServer":
        normalized_transport = str(transport or "").strip().lower()
        if normalized_transport not in _SUPPORTED_TRANSPORTS:
            raise ValueError(f"Transporte MCP no soportado: {transport}")
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("El servidor MCP necesita un nombre")
        if normalized_transport == "stdio" and not str(command or "").strip():
            raise ValueError("Un servidor MCP stdio necesita 'command'")
        if normalized_transport == "http" and not str(url or "").strip():
            raise ValueError("Un servidor MCP http necesita 'url'")
        return cls(
            server_id=server_id or f"mcp-{uuid.uuid4().hex[:12]}",
            name=normalized_name,
            transport=normalized_transport,
            command=str(command or "").strip(),
            args=list(args or []),
            url=str(url or "").strip(),
            secret_ref=str(secret_ref or "").strip(),
            enabled=bool(enabled),
            source=str(source or "chat").strip() or "chat",
        ).touched()

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DesktopMCPServer":
        return cls(
            server_id=str(row["server_id"]),
            name=str(row["name"]),
            transport=str(row["transport"]),
            command=str(row["command"]),
            args=list(json.loads(row["args_json"] or "[]")),
            url=str(row["url"]),
            secret_ref=str(row["secret_ref"]),
            enabled=bool(row["enabled"]),
            source=str(row["source"]),
            updated_at=str(row["updated_at"]),
        )

    def touched(self) -> "DesktopMCPServer":
        return DesktopMCPServer(
            server_id=self.server_id,
            name=self.name,
            transport=self.transport,
            command=self.command,
            args=list(self.args),
            url=self.url,
            secret_ref=self.secret_ref,
            enabled=self.enabled,
            source=self.source,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DesktopMCPServerStore:
    """Persiste los servidores MCP conectados por el usuario via chat/config."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def list_servers(self, *, enabled_only: bool = False) -> list[DesktopMCPServer]:
        query = "SELECT * FROM mcp_servers"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name COLLATE NOCASE ASC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [DesktopMCPServer.from_row(row) for row in rows]

    def get_server(self, server_id: str) -> DesktopMCPServer | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE server_id = ?", (server_id,)
            ).fetchone()
        return DesktopMCPServer.from_row(row) if row is not None else None

    def get_by_name(self, name: str) -> DesktopMCPServer | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_servers WHERE name = ?", (str(name or "").strip(),)
            ).fetchone()
        return DesktopMCPServer.from_row(row) if row is not None else None

    def save_server(self, server: DesktopMCPServer) -> DesktopMCPServer:
        server = server.touched()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mcp_servers (
                    server_id, name, transport, command, args_json, url,
                    secret_ref, enabled, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id) DO UPDATE SET
                    name = excluded.name,
                    transport = excluded.transport,
                    command = excluded.command,
                    args_json = excluded.args_json,
                    url = excluded.url,
                    secret_ref = excluded.secret_ref,
                    enabled = excluded.enabled,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    server.server_id,
                    server.name,
                    server.transport,
                    server.command,
                    json.dumps(server.args),
                    server.url,
                    server.secret_ref,
                    int(server.enabled),
                    server.source,
                    server.updated_at,
                ),
            )
            conn.commit()
        return server

    def delete_server(self, server_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM mcp_servers WHERE server_id = ?", (server_id,)
            )
            conn.commit()
        return result.rowcount > 0
