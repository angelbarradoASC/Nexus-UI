"""SQLite-backed conversation history for PEPO (Nexus Desktop).

Mismo idioma que `desktop/storage/monitoring_integrations.py`: sqlite3
directo, sin WAL/async — uso local de un solo usuario, no hace falta más.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at);
"""

_TITLE_MAX_LEN = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_title(first_message: str) -> str:
    text = " ".join((first_message or "").split())
    if len(text) <= _TITLE_MAX_LEN:
        return text or "Nueva conversación"
    return text[:_TITLE_MAX_LEN].rstrip() + "…"


@dataclass(slots=True)
class PepoConversation:
    id: str
    title: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PepoConversation":
        return cls(
            id=str(row["id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title, "created_at": self.created_at, "updated_at": self.updated_at}


@dataclass(slots=True)
class PepoMessage:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PepoMessage":
        return cls(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
        )

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "role": self.role, "content": self.content, "created_at": self.created_at}


class PepoConversationStore:
    """Persiste conversaciones + mensajes de PEPO. Sin borrar/renombrar/
    favoritos/carpetas — no forma parte de lo pedido."""

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

    def list_conversations(self, *, limit: int = 50) -> list[PepoConversation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [PepoConversation.from_row(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> PepoConversation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return PepoConversation.from_row(row) if row else None

    def create_conversation(self, first_message: str) -> PepoConversation:
        now = _now_iso()
        conversation = PepoConversation(
            id=f"pconv-{uuid.uuid4().hex[:12]}",
            title=_make_title(first_message),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation.id, conversation.title, conversation.created_at, conversation.updated_at),
            )
            conn.commit()
        return conversation

    def get_messages(self, conversation_id: str) -> list[PepoMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        return [PepoMessage.from_row(row) for row in rows]

    def append_turn(self, conversation_id: str, *, user_message: str, assistant_message: str) -> None:
        """Inserta el turno (mensaje de usuario + respuesta) y refresca
        updated_at — una sola transacción."""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
                (f"pmsg-{uuid.uuid4().hex[:12]}", conversation_id, user_message, now),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                (f"pmsg-{uuid.uuid4().hex[:12]}", conversation_id, assistant_message, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()
