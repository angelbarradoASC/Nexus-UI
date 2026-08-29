"""SQLite-backed persistence for pending human-confirmation actions.

Los 5 agentes locales de PEPO con confirmacion en dos pasos (Mouse,
SystemTask, RemoteOps, SelfConfig, MCP) guardaban su estado pendiente SOLO
en un `dict` en memoria — si el proceso se reinicia a mitad de una
confirmacion (por ejemplo, justo antes de guardar una credencial en el
Vault, o de escribir en un servidor MCP), esa propuesta desaparecia sin
avisar a nadie.

Este store la persiste. Cada agente sigue leyendo/escribiendo su propio
dict en memoria como antes (hot path sin tocar — sigue siendo la fuente de
lectura normal), pero escribe a la vez aqui (write-through) y rehidrata el
dict desde aqui al arrancar (`load_pending_from_store()` en cada agente).

Deliberadamente generico (una fila por `agent_id`+`context_id`, con un
`payload_json` de forma libre) para servir a los 5 agentes sin que cada
uno necesite su propia tabla — cada uno decide que campos propios mete en
el payload (ver `_to_store_payload()`/`_from_store_row()` de cada agente).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_actions (
    agent_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    task TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    messages_json TEXT NOT NULL DEFAULT '[]',
    tool_call_id TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, context_id)
);
"""


@dataclass(slots=True)
class StoredPendingAction:
    agent_id: str
    context_id: str
    kind: str
    task: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StoredPendingAction":
        return cls(
            agent_id=str(row["agent_id"]),
            context_id=str(row["context_id"]),
            kind=str(row["kind"]),
            task=str(row["task"]),
            payload=json.loads(row["payload_json"] or "{}"),
            messages=json.loads(row["messages_json"] or "[]"),
            tool_call_id=row["tool_call_id"],
            updated_at=str(row["updated_at"]),
        )


class DesktopPendingActionStore:
    """Persiste el estado pendiente de los 5 agentes locales de PEPO con
    confirmacion en dos pasos. Ver docstring del modulo."""

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

    def save(
        self,
        *,
        agent_id: str,
        context_id: str,
        kind: str,
        task: str = "",
        payload: dict[str, Any] | None = None,
        messages: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    agent_id, context_id, kind, task, payload_json,
                    messages_json, tool_call_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, context_id) DO UPDATE SET
                    kind = excluded.kind,
                    task = excluded.task,
                    payload_json = excluded.payload_json,
                    messages_json = excluded.messages_json,
                    tool_call_id = excluded.tool_call_id,
                    updated_at = excluded.updated_at
                """,
                (
                    agent_id,
                    context_id,
                    kind,
                    task,
                    json.dumps(payload or {}),
                    json.dumps(messages or []),
                    tool_call_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def delete(self, *, agent_id: str, context_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM pending_actions WHERE agent_id = ? AND context_id = ?",
                (agent_id, context_id),
            )
            conn.commit()

    def list_for_agent(self, agent_id: str) -> list[StoredPendingAction]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_actions WHERE agent_id = ? ORDER BY updated_at ASC",
                (agent_id,),
            ).fetchall()
        return [StoredPendingAction.from_row(row) for row in rows]
