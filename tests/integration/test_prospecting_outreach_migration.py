from __future__ import annotations

import json
import sqlite3

import pytest

from nexus.outreach.repository import OutreachRepository
from nexus.prospecting.repository import ProspectingRepository


@pytest.mark.asyncio
async def test_prospecting_and_outreach_migration_preserves_payloads_and_keeps_legacy_files(tmp_path):
    prospecting_dir = tmp_path / "prospecting"
    outreach_dir = tmp_path / "outreach"
    prospecting_dir.mkdir(parents=True, exist_ok=True)
    outreach_dir.mkdir(parents=True, exist_ok=True)

    prospecting_payload = [
        {
            "run_id": "pros-legacy-1",
            "status": "completed",
            "started_at": "2026-06-21T10:00:00+00:00",
            "brief": {"vertical": "restaurants", "city": "Zaragoza"},
            "results": [{"result_id": "r1", "name": "Lead 1"}],
            "summary": {"usable_results": 1},
        }
    ]
    campaigns_payload = [
        {
            "campaign_id": "out-legacy-1",
            "campaign_name": "Legacy",
            "created_at": "2026-06-21T10:00:00+00:00",
            "updated_at": "2026-06-21T10:01:00+00:00",
            "max_daily_send": 5,
            "followup_delays_days": [4, 9],
            "prospects": [{"email": "legacy@example.com", "current_step": 0, "history": [], "status": "pending", "next_due_at": "2026-06-21T10:00:00+00:00"}],
        }
    ]
    events_payload = [
        {
            "event_id": "evt-legacy-1",
            "campaign_id": "out-legacy-1",
            "event_type": "email_preview",
            "timestamp": "2026-06-21T10:02:00+00:00",
            "recipient_email": "legacy@example.com",
        }
    ]

    (prospecting_dir / "prospecting_runs.json").write_text(
        json.dumps(prospecting_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (outreach_dir / "campaigns.json").write_text(
        json.dumps(campaigns_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (outreach_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events_payload) + "\n",
        encoding="utf-8",
    )

    prospecting_repo = ProspectingRepository(prospecting_dir)
    outreach_repo = OutreachRepository(outreach_dir)

    runs = await prospecting_repo.load_runs()
    campaigns = await outreach_repo.load_campaigns()
    events = await outreach_repo.list_events(limit=10)

    assert runs == prospecting_payload
    assert campaigns == campaigns_payload
    assert events == events_payload
    assert (prospecting_dir / "prospecting_runs.json").exists()
    assert (outreach_dir / "campaigns.json").exists()
    assert (outreach_dir / "events.jsonl").exists()
    assert len(list(prospecting_dir.glob("prospecting_runs.migrated-backup-*.json"))) == 1
    assert len(list(outreach_dir.glob("campaigns.migrated-backup-*.json"))) == 1
    assert len(list(outreach_dir.glob("events.migrated-backup-*.jsonl"))) == 1

    prospecting_conn = sqlite3.connect(prospecting_dir / "prospecting.sqlite3")
    prospecting_migration = prospecting_conn.execute(
        "SELECT result, record_count FROM storage_migrations WHERE migration_scope = 'prospecting_runs'"
    ).fetchone()
    prospecting_conn.close()
    assert prospecting_migration == ("success", 1)

    outreach_conn = sqlite3.connect(outreach_dir / "outreach.sqlite3")
    outreach_migrations = outreach_conn.execute(
        "SELECT migration_scope, result, record_count FROM storage_migrations ORDER BY migration_scope"
    ).fetchall()
    outreach_conn.close()
    assert outreach_migrations == [
        ("outreach_campaigns", "success", 1),
        ("outreach_events", "success", 1),
    ]
