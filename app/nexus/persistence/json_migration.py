from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.persistence.sqlite_store import SQLiteStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write_backup_once(source_path: Path) -> None:
    if not source_path.exists():
        return
    pattern = f"{source_path.stem}.migrated-backup-*{source_path.suffix}"
    if any(source_path.parent.glob(pattern)):
        return
    backup_path = source_path.with_name(
        f"{source_path.stem}.migrated-backup-{_timestamp_slug()}{source_path.suffix}"
    )
    backup_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")


def _record_migration_result(
    store: SQLiteStore,
    *,
    migration_scope: str,
    source_path: Path,
    source_hash: str,
    result: str,
    record_count: int,
    details: dict[str, Any],
) -> None:
    with store.transaction() as conn:
        conn.execute(
            """
            INSERT INTO storage_migrations(
                migration_scope,
                source_path,
                source_hash,
                result,
                record_count,
                migrated_at,
                details_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(migration_scope, source_path, source_hash, result)
            DO UPDATE SET
                record_count=excluded.record_count,
                migrated_at=excluded.migrated_at,
                details_json=excluded.details_json
            """,
            (
                migration_scope,
                str(source_path),
                source_hash,
                result,
                record_count,
                _now_iso(),
                json.dumps(details, ensure_ascii=False),
            ),
        )


def _has_successful_migration(
    store: SQLiteStore,
    *,
    migration_scope: str,
    source_path: Path,
    source_hash: str,
) -> bool:
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM storage_migrations
            WHERE migration_scope = ?
              AND source_path = ?
              AND source_hash = ?
              AND result = 'success'
            LIMIT 1
            """,
            (migration_scope, str(source_path), source_hash),
        ).fetchone()
    return row is not None


def _adopt_preexisting_sqlite_state(
    store: SQLiteStore,
    *,
    migration_scope: str,
    source_path: Path,
    source_hash: str,
    record_count: int,
) -> None:
    _record_migration_result(
        store,
        migration_scope=migration_scope,
        source_path=source_path,
        source_hash=source_hash,
        result="success",
        record_count=record_count,
        details={"adopted_existing_sqlite": True, "records": record_count},
    )


def _insert_prospecting_rows(store: SQLiteStore, runs: list[dict[str, Any]]) -> None:
    now = _now_iso()
    with store.transaction() as conn:
        for index, payload in enumerate(runs):
            run_id = str(payload.get("run_id") or f"migrated-run-{index}")
            created_at = str(payload.get("started_at") or payload.get("created_at") or now)
            updated_at = str(payload.get("finished_at") or payload.get("updated_at") or created_at)
            conn.execute(
                """
                INSERT INTO prospecting_runs(run_id, payload_json, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (run_id, json.dumps(payload, ensure_ascii=False), created_at, updated_at),
            )
        conn.execute(
            """
            INSERT INTO prospecting_meta(key, value_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (
                "json_migration",
                json.dumps({"migrated": True, "runs": len(runs), "at": now}, ensure_ascii=False),
                now,
            ),
        )


def _insert_outreach_rows(
    store: SQLiteStore,
    campaigns: list[dict[str, Any]],
    events: list[dict[str, Any]],
    prompt: str | None,
) -> None:
    now = _now_iso()
    with store.transaction() as conn:
        for index, payload in enumerate(campaigns):
            campaign_id = str(payload.get("campaign_id") or f"migrated-campaign-{index}")
            created_at = str(payload.get("created_at") or now)
            updated_at = str(payload.get("updated_at") or created_at)
            conn.execute(
                """
                INSERT INTO outreach_campaigns(campaign_id, payload_json, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (campaign_id, json.dumps(payload, ensure_ascii=False), created_at, updated_at),
            )
        for index, payload in enumerate(events):
            event_id = str(payload.get("event_id") or f"migrated-event-{index}")
            campaign_id = payload.get("campaign_id")
            created_at = str(payload.get("timestamp") or payload.get("created_at") or now)
            conn.execute(
                """
                INSERT INTO outreach_events(event_id, campaign_id, payload_json, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (event_id, campaign_id, json.dumps(payload, ensure_ascii=False), created_at),
            )
        if prompt is not None:
            conn.execute(
                """
                INSERT INTO outreach_meta(key, value_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                ("prompt", json.dumps({"prompt": prompt}, ensure_ascii=False), now),
            )
        conn.execute(
            """
            INSERT INTO outreach_meta(key, value_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (
                "json_migration",
                json.dumps(
                    {"migrated": True, "campaigns": len(campaigns), "events": len(events), "at": now},
                    ensure_ascii=False,
                ),
                now,
            ),
        )


def migrate_prospecting_json_if_needed(
    *,
    store: SQLiteStore,
    source_path: Path,
) -> None:
    if not source_path.exists():
        return
    raw_content = source_path.read_text(encoding="utf-8")
    source_hash = _sha256_text(raw_content)
    if _has_successful_migration(
        store,
        migration_scope="prospecting_runs",
        source_path=source_path,
        source_hash=source_hash,
    ):
        return
    with store.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM prospecting_runs").fetchone()
    if row is not None and int(row["total"]) > 0:
        _adopt_preexisting_sqlite_state(
            store,
            migration_scope="prospecting_runs",
            source_path=source_path,
            source_hash=source_hash,
            record_count=int(row["total"]),
        )
        return

    payload = json.loads(raw_content)
    if not isinstance(payload, list):
        raise ValueError("El JSON heredado de prospecting debe contener una lista de runs.")

    _write_backup_once(source_path)
    try:
        _insert_prospecting_rows(store, payload)
    except Exception as exc:
        _record_migration_result(
            store,
            migration_scope="prospecting_runs",
            source_path=source_path,
            source_hash=source_hash,
            result="failed",
            record_count=0,
            details={"error": str(exc)},
        )
        raise
    _record_migration_result(
        store,
        migration_scope="prospecting_runs",
        source_path=source_path,
        source_hash=source_hash,
        result="success",
        record_count=len(payload),
        details={"records": len(payload)},
    )


def migrate_outreach_json_if_needed(
    *,
    store: SQLiteStore,
    campaigns_path: Path,
    events_path: Path,
    prompt_path: Path,
) -> None:
    if not campaigns_path.exists() and not events_path.exists() and not prompt_path.exists():
        return
    campaigns: list[dict[str, Any]] = []
    campaign_hash: str | None = None
    if campaigns_path.exists():
        raw_campaigns = campaigns_path.read_text(encoding="utf-8")
        campaign_hash = _sha256_text(raw_campaigns)
        loaded_campaigns = json.loads(raw_campaigns)
        if not isinstance(loaded_campaigns, list):
            raise ValueError("El JSON heredado de outreach campaigns debe contener una lista.")
        campaigns = loaded_campaigns

    events: list[dict[str, Any]] = []
    events_hash: str | None = None
    if events_path.exists():
        raw_events = events_path.read_text(encoding="utf-8")
        events_hash = _sha256_text(raw_events)
        for raw_line in raw_events.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Cada linea de events.jsonl debe ser un objeto JSON.")
            events.append(payload)

    prompt: str | None = None
    prompt_hash: str | None = None
    if prompt_path.exists():
        raw_prompt = prompt_path.read_text(encoding="utf-8")
        prompt_hash = _sha256_text(raw_prompt)
        prompt = raw_prompt.strip() or None

    existing_success = []
    if campaign_hash is not None:
        existing_success.append(
            _has_successful_migration(
                store,
                migration_scope="outreach_campaigns",
                source_path=campaigns_path,
                source_hash=campaign_hash,
            )
        )
    if events_hash is not None:
        existing_success.append(
            _has_successful_migration(
                store,
                migration_scope="outreach_events",
                source_path=events_path,
                source_hash=events_hash,
            )
        )
    if prompt_hash is not None:
        existing_success.append(
            _has_successful_migration(
                store,
                migration_scope="outreach_prompt",
                source_path=prompt_path,
                source_hash=prompt_hash,
            )
        )
    if existing_success and all(existing_success):
        return

    with store.connect() as conn:
        campaign_row = conn.execute("SELECT COUNT(*) AS total FROM outreach_campaigns").fetchone()
        event_row = conn.execute("SELECT COUNT(*) AS total FROM outreach_events").fetchone()
    if campaign_row is not None and event_row is not None and (
        int(campaign_row["total"]) > 0 or int(event_row["total"]) > 0
    ):
        if campaign_hash is not None:
            _adopt_preexisting_sqlite_state(
                store,
                migration_scope="outreach_campaigns",
                source_path=campaigns_path,
                source_hash=campaign_hash,
                record_count=int(campaign_row["total"]),
            )
        if events_hash is not None:
            _adopt_preexisting_sqlite_state(
                store,
                migration_scope="outreach_events",
                source_path=events_path,
                source_hash=events_hash,
                record_count=int(event_row["total"]),
            )
        if prompt_hash is not None:
            _adopt_preexisting_sqlite_state(
                store,
                migration_scope="outreach_prompt",
                source_path=prompt_path,
                source_hash=prompt_hash,
                record_count=1 if prompt is not None else 0,
            )
        return

    _write_backup_once(campaigns_path)
    _write_backup_once(events_path)
    _write_backup_once(prompt_path)
    try:
        _insert_outreach_rows(store, campaigns, events, prompt)
    except Exception as exc:
        if campaign_hash is not None:
            _record_migration_result(
                store,
                migration_scope="outreach_campaigns",
                source_path=campaigns_path,
                source_hash=campaign_hash,
                result="failed",
                record_count=0,
                details={"error": str(exc)},
            )
        if events_hash is not None:
            _record_migration_result(
                store,
                migration_scope="outreach_events",
                source_path=events_path,
                source_hash=events_hash,
                result="failed",
                record_count=0,
                details={"error": str(exc)},
            )
        if prompt_hash is not None:
            _record_migration_result(
                store,
                migration_scope="outreach_prompt",
                source_path=prompt_path,
                source_hash=prompt_hash,
                result="failed",
                record_count=0,
                details={"error": str(exc)},
            )
        raise
    if campaign_hash is not None:
        _record_migration_result(
            store,
            migration_scope="outreach_campaigns",
            source_path=campaigns_path,
            source_hash=campaign_hash,
            result="success",
            record_count=len(campaigns),
            details={"records": len(campaigns)},
        )
    if events_hash is not None:
        _record_migration_result(
            store,
            migration_scope="outreach_events",
            source_path=events_path,
            source_hash=events_hash,
            result="success",
            record_count=len(events),
            details={"records": len(events)},
        )
    if prompt_hash is not None:
        _record_migration_result(
            store,
            migration_scope="outreach_prompt",
            source_path=prompt_path,
            source_hash=prompt_hash,
            result="success",
            record_count=1 if prompt is not None else 0,
            details={"has_prompt": prompt is not None},
        )
