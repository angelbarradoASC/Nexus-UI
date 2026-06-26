"""File-backed persistence for prospecting runs and raw search evidence."""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.persistence.json_migration import migrate_prospecting_json_if_needed
from nexus.persistence.prospecting_schema import ensure_prospecting_schema
from nexus.persistence.sqlite_store import SQLiteStore
from nexus.storage.json_files import load_json_list, write_json_atomic


class ProspectingRepository:
    """Store prospecting runs in SQLite plus raw search evidence in JSON files."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._runs_path = self._data_dir / "prospecting_runs.json"
        self._legacy_runs_path = self._data_dir / "municipal_runs.json"
        self._storage_backend = str(os.environ.get("NEXUS_PROSPECTING_STORAGE_BACKEND") or "sqlite").lower()
        self._db_path = Path(
            os.environ.get("NEXUS_PROSPECTING_DB_PATH") or (self._data_dir / "prospecting.sqlite3")
        )
        self._raw_dir = self._data_dir / "raw"
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        if self._storage_backend == "json":
            self._store = None
            return
        self._store = SQLiteStore(self._db_path)
        ensure_prospecting_schema(self._store)
        source_path = self._runs_path if self._runs_path.exists() else self._legacy_runs_path
        migrate_prospecting_json_if_needed(store=self._store, source_path=source_path)

    async def load_runs(self) -> list[dict[str, Any]]:
        if self._storage_backend == "json":
            source_path = self._runs_path if self._runs_path.exists() else self._legacy_runs_path
            return load_json_list(source_path)
        with self._store.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM prospecting_runs ORDER BY rowid"
            ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    async def save_runs(self, runs: list[dict[str, Any]]) -> None:
        if self._storage_backend == "json":
            write_json_atomic(self._runs_path, runs)
            return
        existing = await self.load_runs()
        existing_created_at = {
            self._payload_run_id(item, index): str(item.get("started_at") or item.get("created_at") or self._now_iso())
            for index, item in enumerate(existing)
        }
        now = self._now_iso()
        with self._store.transaction() as conn:
            conn.execute("DELETE FROM prospecting_runs")
            for index, run in enumerate(runs):
                run_key = self._payload_run_id(run, index)
                created_at = existing_created_at.get(run_key) or str(
                    run.get("started_at") or run.get("created_at") or now
                )
                updated_at = str(run.get("finished_at") or run.get("updated_at") or now)
                conn.execute(
                    """
                    INSERT INTO prospecting_runs(run_id, payload_json, created_at, updated_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (run_key, json.dumps(run, ensure_ascii=False), created_at, updated_at),
                )

    async def append_run(self, run: dict[str, Any]) -> None:
        if self._storage_backend == "json":
            runs = await self.load_runs()
            runs.append(run)
            write_json_atomic(self._runs_path, runs)
            return
        now = self._now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO prospecting_runs(run_id, payload_json, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (
                    self._payload_run_id(run, 0),
                    json.dumps(run, ensure_ascii=False),
                    str(run.get("started_at") or run.get("created_at") or now),
                    str(run.get("finished_at") or run.get("updated_at") or now),
                ),
            )

    async def update_run(self, run_id: str, updater) -> dict[str, Any] | None:
        if self._storage_backend == "json":
            runs = await self.load_runs()
            for index, run in enumerate(runs):
                if self._payload_run_id(run, index) != run_id:
                    continue
                updated = updater(run) or run
                runs[index] = updated
                write_json_atomic(self._runs_path, runs)
                return updated
            return None
        with self._store.transaction() as conn:
            row = conn.execute(
                "SELECT payload_json, created_at FROM prospecting_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = json.loads(str(row["payload_json"]))
            updated = updater(run) or run
            conn.execute(
                """
                UPDATE prospecting_runs
                SET payload_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (json.dumps(updated, ensure_ascii=False), self._now_iso(), run_id),
            )
            return updated

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        if self._storage_backend == "json":
            runs = await self.load_runs()
            return next((run for index, run in enumerate(runs) if self._payload_run_id(run, index) == run_id), None)
        with self._store.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM prospecting_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["payload_json"]))

    async def save_raw_search(self, run_id: str, provider: str, query: str, payload: dict[str, Any]) -> Path:
        safe_query = "".join(ch if ch.isalnum() else "_" for ch in query.lower())[:80].strip("_") or "query"
        timestamp = payload.get("timestamp") or "unknown"
        filename = f"{run_id}_{provider}_{safe_query}_{timestamp.replace(':', '-')}.json"
        target = self._raw_dir / filename
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    @staticmethod
    def _payload_run_id(payload: dict[str, Any], index: int) -> str:
        return str(payload.get("run_id") or f"run-{index}")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
