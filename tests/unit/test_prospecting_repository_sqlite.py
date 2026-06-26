from __future__ import annotations

import json
import os
import sqlite3

import pytest

from nexus.prospecting.repository import ProspectingRepository


def _sample_run(run_id: str, city: str = "Zaragoza") -> dict:
    return {
        "run_id": run_id,
        "status": "completed",
        "started_at": "2026-06-21T10:00:00+00:00",
        "finished_at": "2026-06-21T10:05:00+00:00",
        "brief": {"vertical": "restaurants", "city": city},
        "queries": [f"[Places] restaurantes {city}"],
        "results": [{"result_id": f"res-{run_id}", "name": f"Lead {run_id}"}],
        "discarded": [],
        "summary": {"usable_results": 1},
    }


@pytest.mark.asyncio
async def test_prospecting_repository_migrates_legacy_json_to_sqlite(tmp_path):
    data_dir = tmp_path / "prospecting"
    data_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = data_dir / "prospecting_runs.json"
    legacy_runs = [_sample_run("pros-1"), _sample_run("pros-2", city="Madrid")]
    legacy_path.write_text(json.dumps(legacy_runs, ensure_ascii=False, indent=2), encoding="utf-8")

    repo = ProspectingRepository(data_dir)
    loaded = await repo.load_runs()

    assert [item["run_id"] for item in loaded] == ["pros-1", "pros-2"]
    assert loaded[1]["brief"]["city"] == "Madrid"
    assert legacy_path.exists()
    assert len(list(data_dir.glob("prospecting_runs.migrated-backup-*.json"))) == 1
    assert (data_dir / "prospecting.sqlite3").exists()
    conn = sqlite3.connect(data_dir / "prospecting.sqlite3")
    migration_row = conn.execute(
        """
        SELECT source_path, source_hash, result, record_count
        FROM storage_migrations
        WHERE migration_scope = 'prospecting_runs'
        """
    ).fetchone()
    conn.close()
    assert migration_row is not None
    assert migration_row[0].endswith("prospecting_runs.json")
    assert migration_row[2] == "success"
    assert migration_row[3] == 2


@pytest.mark.asyncio
async def test_prospecting_repository_second_init_does_not_duplicate(tmp_path):
    data_dir = tmp_path / "prospecting"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "prospecting_runs.json").write_text(
        json.dumps([_sample_run("pros-1")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    repo1 = ProspectingRepository(data_dir)
    first = await repo1.load_runs()
    repo2 = ProspectingRepository(data_dir)
    second = await repo2.load_runs()

    assert len(first) == 1
    assert len(second) == 1
    assert second[0]["run_id"] == "pros-1"
    conn = sqlite3.connect(data_dir / "prospecting.sqlite3")
    total = conn.execute(
        """
        SELECT COUNT(*)
        FROM storage_migrations
        WHERE migration_scope = 'prospecting_runs' AND result = 'success'
        """
    ).fetchone()[0]
    conn.close()
    assert total == 1


@pytest.mark.asyncio
async def test_prospecting_repository_two_instances_append_without_losing_runs(tmp_path):
    data_dir = tmp_path / "prospecting"
    repo1 = ProspectingRepository(data_dir)
    repo2 = ProspectingRepository(data_dir)

    await repo1.append_run(_sample_run("pros-1"))
    await repo2.append_run(_sample_run("pros-2"))
    loaded = await repo1.load_runs()

    assert [item["run_id"] for item in loaded] == ["pros-1", "pros-2"]


@pytest.mark.asyncio
async def test_prospecting_repository_migration_failure_keeps_json_and_no_partial_sqlite(tmp_path, monkeypatch):
    data_dir = tmp_path / "prospecting"
    data_dir.mkdir(parents=True, exist_ok=True)
    source_path = data_dir / "prospecting_runs.json"
    source_payload = [_sample_run("pros-1")]
    source_path.write_text(json.dumps(source_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("forced migration failure")

    monkeypatch.setattr("nexus.persistence.json_migration._insert_prospecting_rows", _boom)

    with pytest.raises(RuntimeError, match="forced migration failure"):
        ProspectingRepository(data_dir)

    assert json.loads(source_path.read_text(encoding="utf-8")) == source_payload
    db_path = data_dir / "prospecting.sqlite3"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        total = conn.execute("SELECT COUNT(*) FROM prospecting_runs").fetchone()[0]
        migration = conn.execute(
            """
            SELECT result, record_count
            FROM storage_migrations
            WHERE migration_scope = 'prospecting_runs'
            """
        ).fetchone()
        conn.close()
        assert total == 0
        assert migration is not None
        assert migration[0] == "failed"
        assert migration[1] == 0


@pytest.mark.asyncio
async def test_prospecting_repository_duplicate_run_id_rolls_back_whole_migration(tmp_path):
    data_dir = tmp_path / "prospecting"
    data_dir.mkdir(parents=True, exist_ok=True)
    source_path = data_dir / "prospecting_runs.json"
    source_path.write_text(
        json.dumps([_sample_run("dup-1"), _sample_run("dup-1")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        ProspectingRepository(data_dir)

    conn = sqlite3.connect(data_dir / "prospecting.sqlite3")
    total = conn.execute("SELECT COUNT(*) FROM prospecting_runs").fetchone()[0]
    migration = conn.execute(
        """
        SELECT result
        FROM storage_migrations
        WHERE migration_scope = 'prospecting_runs'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    assert total == 0
    assert migration is not None
    assert migration[0] == "failed"


@pytest.mark.asyncio
async def test_prospecting_repository_json_backend_flag_restores_legacy_mode(tmp_path, monkeypatch):
    data_dir = tmp_path / "prospecting"
    data_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = data_dir / "prospecting_runs.json"
    legacy_path.write_text(json.dumps([_sample_run("pros-json")], ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setenv("NEXUS_PROSPECTING_STORAGE_BACKEND", "json")
    repo = ProspectingRepository(data_dir)
    loaded = await repo.load_runs()
    await repo.append_run(_sample_run("pros-json-2"))

    assert [item["run_id"] for item in loaded] == ["pros-json"]
    assert [item["run_id"] for item in await repo.load_runs()] == ["pros-json", "pros-json-2"]
    assert not (data_dir / "prospecting.sqlite3").exists()
    monkeypatch.delenv("NEXUS_PROSPECTING_STORAGE_BACKEND", raising=False)
