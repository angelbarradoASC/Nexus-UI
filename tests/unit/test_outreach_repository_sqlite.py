from __future__ import annotations

import json
import sqlite3

import pytest

from nexus.outreach.repository import OutreachRepository


def _sample_campaign(campaign_id: str, email: str = "a@example.com") -> dict:
    return {
        "campaign_id": campaign_id,
        "campaign_name": f"Campaign {campaign_id}",
        "created_at": "2026-06-21T10:00:00+00:00",
        "updated_at": "2026-06-21T10:05:00+00:00",
        "max_daily_send": 10,
        "followup_delays_days": [4, 9],
        "prospects": [
            {
                "prospect_id": f"pros-{campaign_id}",
                "email": email,
                "status": "pending",
                "current_step": 0,
                "history": [],
                "next_due_at": "2026-06-21T10:00:00+00:00",
            }
        ],
    }


def _sample_event(event_id: str, campaign_id: str) -> dict:
    return {
        "event_id": event_id,
        "campaign_id": campaign_id,
        "event_type": "email_preview",
        "timestamp": "2026-06-21T10:10:00+00:00",
        "recipient_email": "a@example.com",
    }


@pytest.mark.asyncio
async def test_outreach_repository_migrates_json_and_jsonl_to_sqlite(tmp_path):
    data_dir = tmp_path / "outreach"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "campaigns.json").write_text(
        json.dumps([_sample_campaign("out-1")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (data_dir / "events.jsonl").write_text(
        json.dumps(_sample_event("evt-1", "out-1"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (data_dir / "outreach_prompt.txt").write_text("Prompt legado", encoding="utf-8")

    repo = OutreachRepository(data_dir)
    campaigns = await repo.load_campaigns()
    events = await repo.list_events(limit=10)
    prompt = await repo.load_prompt()

    assert campaigns[0]["campaign_id"] == "out-1"
    assert events[0]["event_id"] == "evt-1"
    assert prompt == "Prompt legado"
    assert len(list(data_dir.glob("campaigns.migrated-backup-*.json"))) == 1
    assert len(list(data_dir.glob("events.migrated-backup-*.jsonl"))) == 1
    assert len(list(data_dir.glob("outreach_prompt.migrated-backup-*.txt"))) == 1
    assert (data_dir / "outreach.sqlite3").exists()
    conn = sqlite3.connect(data_dir / "outreach.sqlite3")
    rows = conn.execute(
        """
        SELECT migration_scope, result, record_count
        FROM storage_migrations
        ORDER BY migration_scope
        """
    ).fetchall()
    conn.close()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("outreach_campaigns", "success", 1),
        ("outreach_events", "success", 1),
        ("outreach_prompt", "success", 1),
    ]


@pytest.mark.asyncio
async def test_outreach_repository_second_init_does_not_duplicate(tmp_path):
    data_dir = tmp_path / "outreach"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "campaigns.json").write_text(
        json.dumps([_sample_campaign("out-1")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    repo1 = OutreachRepository(data_dir)
    repo2 = OutreachRepository(data_dir)
    campaigns1 = await repo1.load_campaigns()
    campaigns2 = await repo2.load_campaigns()

    assert len(campaigns1) == 1
    assert len(campaigns2) == 1
    conn = sqlite3.connect(data_dir / "outreach.sqlite3")
    total = conn.execute(
        """
        SELECT COUNT(*)
        FROM storage_migrations
        WHERE result = 'success'
        """
    ).fetchone()[0]
    conn.close()
    assert total == 1


@pytest.mark.asyncio
async def test_outreach_repository_two_instances_append_without_losing_events(tmp_path):
    data_dir = tmp_path / "outreach"
    repo1 = OutreachRepository(data_dir)
    repo2 = OutreachRepository(data_dir)

    await repo1.save_campaigns([_sample_campaign("out-1")])
    await repo1.append_event(_sample_event("evt-1", "out-1"))
    await repo2.append_event(_sample_event("evt-2", "out-1"))
    events = await repo1.list_events(limit=10)

    assert [item["event_id"] for item in events] == ["evt-2", "evt-1"]


@pytest.mark.asyncio
async def test_outreach_repository_migration_failure_keeps_sources_and_no_partial_sqlite(tmp_path, monkeypatch):
    data_dir = tmp_path / "outreach"
    data_dir.mkdir(parents=True, exist_ok=True)
    campaigns = [_sample_campaign("out-1")]
    events_line = json.dumps(_sample_event("evt-1", "out-1"), ensure_ascii=False) + "\n"
    campaigns_path = data_dir / "campaigns.json"
    events_path = data_dir / "events.jsonl"
    campaigns_path.write_text(json.dumps(campaigns, ensure_ascii=False, indent=2), encoding="utf-8")
    events_path.write_text(events_line, encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("forced outreach migration failure")

    monkeypatch.setattr("nexus.persistence.json_migration._insert_outreach_rows", _boom)

    with pytest.raises(RuntimeError, match="forced outreach migration failure"):
        OutreachRepository(data_dir)

    assert json.loads(campaigns_path.read_text(encoding="utf-8")) == campaigns
    assert events_path.read_text(encoding="utf-8") == events_line
    conn = sqlite3.connect(data_dir / "outreach.sqlite3")
    campaigns_total = conn.execute("SELECT COUNT(*) FROM outreach_campaigns").fetchone()[0]
    events_total = conn.execute("SELECT COUNT(*) FROM outreach_events").fetchone()[0]
    migration_results = conn.execute(
        """
        SELECT migration_scope, result
        FROM storage_migrations
        ORDER BY migration_scope
        """
    ).fetchall()
    conn.close()
    assert campaigns_total == 0
    assert events_total == 0
    assert [(row[0], row[1]) for row in migration_results] == [
        ("outreach_campaigns", "failed"),
        ("outreach_events", "failed"),
    ]


@pytest.mark.asyncio
async def test_outreach_repository_duplicate_event_id_rolls_back_whole_migration(tmp_path):
    data_dir = tmp_path / "outreach"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "campaigns.json").write_text(
        json.dumps([_sample_campaign("out-1")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (data_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(_sample_event("evt-dup", "out-1"), ensure_ascii=False),
                json.dumps(_sample_event("evt-dup", "out-1"), ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        OutreachRepository(data_dir)

    conn = sqlite3.connect(data_dir / "outreach.sqlite3")
    campaigns_total = conn.execute("SELECT COUNT(*) FROM outreach_campaigns").fetchone()[0]
    events_total = conn.execute("SELECT COUNT(*) FROM outreach_events").fetchone()[0]
    latest_failure = conn.execute(
        """
        SELECT COUNT(*)
        FROM storage_migrations
        WHERE result = 'failed'
        """
    ).fetchone()[0]
    conn.close()
    assert campaigns_total == 0
    assert events_total == 0
    assert latest_failure >= 1


@pytest.mark.asyncio
async def test_outreach_repository_json_backend_flag_restores_legacy_mode(tmp_path, monkeypatch):
    data_dir = tmp_path / "outreach"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXUS_OUTREACH_STORAGE_BACKEND", "json")
    repo = OutreachRepository(data_dir)

    await repo.save_campaigns([_sample_campaign("out-json")])
    await repo.append_event(_sample_event("evt-json", "out-json"))
    await repo.save_prompt("Prompt plano")

    assert [item["campaign_id"] for item in await repo.load_campaigns()] == ["out-json"]
    assert [item["event_id"] for item in await repo.list_events(limit=10)] == ["evt-json"]
    assert await repo.load_prompt() == "Prompt plano"
    assert not (data_dir / "outreach.sqlite3").exists()
    monkeypatch.delenv("NEXUS_OUTREACH_STORAGE_BACKEND", raising=False)
