"""tests/unit/test_code_routes.py

API de carpetas autorizadas del modo codigo (Desktop-only): lo unico que puede
ampliar o reducir donde puede trabajar el agente de codigo.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from desktop.storage.code_settings import CodeSettingsStore
from products.desktop.backend import code_routes
from products.desktop.backend.code_routes import get_code_settings_store


def _client(tmp_path) -> tuple[TestClient, CodeSettingsStore]:
    store = CodeSettingsStore(tmp_path / "code_settings.json")
    app = FastAPI()
    app.include_router(code_routes.router)
    app.dependency_overrides[get_code_settings_store] = lambda: store
    return TestClient(app), store


def test_settings_start_enabled_and_empty(tmp_path):
    client, _ = _client(tmp_path)

    assert client.get("/api/desktop/code/settings").json() == {
        "enabled": True, "tokens_per_minute": 6500, "llm": {"base_url": "", "model": "", "num_ctx": 8192}, "workspaces": [],
    }


def test_add_and_remove_a_workspace(tmp_path):
    client, store = _client(tmp_path)
    project = tmp_path / "mi_proyecto"
    project.mkdir()

    added = client.post("/api/desktop/code/workspaces", json={"path": str(project)})

    assert added.status_code == 200
    assert added.json()["workspaces"] == [{"path": str(project.resolve()), "name": "mi_proyecto", "exists": True}]
    assert store.is_allowed(project)

    removed = client.post("/api/desktop/code/workspaces/remove", json={"path": str(project)})

    assert removed.json()["workspaces"] == []
    assert not store.is_allowed(project)


def test_adding_a_too_broad_or_missing_folder_is_rejected_with_a_clear_message(tmp_path):
    client, store = _client(tmp_path)

    for bad in (str(Path.home()), str(tmp_path / "no_existe"), "relativa/ruta"):
        response = client.post("/api/desktop/code/workspaces", json={"path": bad})
        assert response.status_code == 422
        assert response.json()["detail"]
    assert store.workspaces() == []


def test_the_switch_can_be_turned_off_and_on(tmp_path):
    client, store = _client(tmp_path)

    assert client.put("/api/desktop/code/enabled", json={"enabled": False}).json()["enabled"] is False
    assert store.enabled is False
    assert client.put("/api/desktop/code/enabled", json={"enabled": True}).json()["enabled"] is True


def test_a_workspace_deleted_from_disk_is_flagged_as_missing(tmp_path):
    client, _ = _client(tmp_path)
    project = tmp_path / "efimero"
    project.mkdir()
    client.post("/api/desktop/code/workspaces", json={"path": str(project)})
    project.rmdir()

    assert client.get("/api/desktop/code/settings").json()["workspaces"][0]["exists"] is False


def test_the_token_quota_can_be_changed_within_limits(tmp_path):
    client, store = _client(tmp_path)

    ok = client.put("/api/desktop/code/limits", json={"tokens_per_minute": 60000})

    assert ok.status_code == 200 and ok.json()["tokens_per_minute"] == 60000
    assert store.tokens_per_minute == 60000
    for bad in (10, 10**9, "mucho"):
        assert client.put("/api/desktop/code/limits", json={"tokens_per_minute": bad}).status_code == 422
    assert store.tokens_per_minute == 60000
