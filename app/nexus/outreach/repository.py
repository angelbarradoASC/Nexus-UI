"""File-backed persistence for outreach campaigns and send events."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.persistence.json_migration import migrate_outreach_json_if_needed
from nexus.persistence.outreach_schema import ensure_outreach_schema
from nexus.persistence.sqlite_store import SQLiteStore
from nexus.storage.json_files import load_json_list, load_jsonl_objects, write_json_atomic, write_jsonl_atomic, write_text_atomic


class OutreachRepository:
    """Stores outreach state in SQLite with legacy JSON migration support."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._campaigns_path = self._data_dir / "campaigns.json"
        self._events_path = self._data_dir / "events.jsonl"
        self._prompt_path = self._data_dir / "outreach_prompt.txt"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._storage_backend = str(os.environ.get("NEXUS_OUTREACH_STORAGE_BACKEND") or "sqlite").lower()
        self._db_path = Path(
            os.environ.get("NEXUS_OUTREACH_DB_PATH") or (self._data_dir / "outreach.sqlite3")
        )
        if self._storage_backend == "json":
            self._store = None
            return
        self._store = SQLiteStore(self._db_path)
        ensure_outreach_schema(self._store)
        migrate_outreach_json_if_needed(
            store=self._store,
            campaigns_path=self._campaigns_path,
            events_path=self._events_path,
            prompt_path=self._prompt_path,
        )

    async def load_campaigns(self) -> list[dict[str, Any]]:
        if self._storage_backend == "json":
            return load_json_list(self._campaigns_path)
        with self._store.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM outreach_campaigns ORDER BY rowid"
            ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    async def save_campaigns(self, campaigns: list[dict[str, Any]]) -> None:
        if self._storage_backend == "json":
            write_json_atomic(self._campaigns_path, campaigns)
            return
        existing = await self.load_campaigns()
        existing_created_at = {
            self._payload_campaign_id(item, index): str(item.get("created_at") or self._now_iso())
            for index, item in enumerate(existing)
        }
        now = self._now_iso()
        with self._store.transaction() as conn:
            conn.execute("DELETE FROM outreach_campaigns")
            for index, campaign in enumerate(campaigns):
                campaign_id = self._payload_campaign_id(campaign, index)
                created_at = existing_created_at.get(campaign_id) or str(campaign.get("created_at") or now)
                updated_at = str(campaign.get("updated_at") or now)
                conn.execute(
                    """
                    INSERT INTO outreach_campaigns(campaign_id, payload_json, created_at, updated_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (campaign_id, json.dumps(campaign, ensure_ascii=False), created_at, updated_at),
                )

    async def append_event(self, event: dict[str, Any]) -> None:
        if self._storage_backend == "json":
            events = load_jsonl_objects(self._events_path)
            events.append(event)
            write_jsonl_atomic(self._events_path, events)
            return
        now = self._now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO outreach_events(event_id, campaign_id, payload_json, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (
                    str(event.get("event_id") or f"event-{now}"),
                    event.get("campaign_id"),
                    json.dumps(event, ensure_ascii=False),
                    str(event.get("timestamp") or event.get("created_at") or now),
                ),
            )

    async def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._storage_backend == "json":
            payloads = load_jsonl_objects(self._events_path)
            if limit <= 0:
                return []
            return list(reversed(payloads[-limit:]))
        with self._store.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM outreach_events ORDER BY rowid"
            ).fetchall()
        payloads = [json.loads(str(row["payload_json"])) for row in rows]
        if limit <= 0:
            return []
        return list(reversed(payloads[-limit:]))

    async def load_prompt(self) -> str | None:
        if self._storage_backend == "json":
            if not self._prompt_path.exists():
                return None
            content = self._prompt_path.read_text(encoding="utf-8").strip()
            return content or None
        with self._store.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM outreach_meta WHERE key = ?",
                ("prompt",),
            ).fetchone()
        if row is not None:
            payload = json.loads(str(row["value_json"]))
            content = str(payload.get("prompt") or "").strip()
            return content or None
        if not self._prompt_path.exists():
            return None
        content = self._prompt_path.read_text(encoding="utf-8").strip()
        return content or None

    async def save_prompt(self, prompt: str) -> None:
        if self._storage_backend == "json":
            write_text_atomic(self._prompt_path, prompt)
            return
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO outreach_meta(key, value_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (
                    "prompt",
                    json.dumps({"prompt": prompt}, ensure_ascii=False),
                    self._now_iso(),
                ),
            )

    @staticmethod
    def _payload_campaign_id(payload: dict[str, Any], index: int) -> str:
        return str(payload.get("campaign_id") or f"campaign-{index}")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
