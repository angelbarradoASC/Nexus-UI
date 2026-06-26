from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.bootstrap import register_nexus_v1
from nexus.prompts.service import PromptManager


@dataclass
class _FakeRuntime:
    coordinator: object
    outreach: object
    crm: object
    prompts: PromptManager


class _FakeCoordinator:
    async def health_snapshot(self):
        return {"status": "ok", "surface": "nexus-v1", "flows": ["chat"], "workers": []}


class _FakeOutreach:
    async def status(self):
        return {
            "status": "success",
            "enabled": False,
            "account": {},
            "daily_cap_default": 20,
            "sent_today": 0,
            "campaigns_total": 0,
            "recent_campaigns": [],
            "recent_events": [],
        }


class _FakeCRM:
    async def status(self):
        return {
            "status": "success",
            "provider": "assets-web-api",
            "discovered_source": "",
            "connector": {"provider": "assets-web-api", "configured": False, "status": "not_configured", "base_url": "", "username": ""},
            "campaigns_total": 0,
            "pending_prospects": 0,
            "recent_campaigns": [],
        }


def _build_client(tmp_path):
    app = FastAPI()
    register_nexus_v1(app)
    app.state.nexus_runtime = _FakeRuntime(
        coordinator=_FakeCoordinator(),
        outreach=_FakeOutreach(),
        crm=_FakeCRM(),
        prompts=PromptManager(tmp_path),
    )
    return TestClient(app, raise_server_exceptions=True)


def test_nexus_prompts_page(tmp_path):
    with _build_client(tmp_path) as client:
        response = client.get("/nexus-prompts")
    assert response.status_code == 200
    assert "Prompting" in response.text
    assert "Guardar prompt" in response.text


def test_nexus_prompts_update_and_reset(tmp_path):
    with _build_client(tmp_path) as client:
        listing = client.get("/api/nexus/prompts")
        update = client.put(
            "/api/nexus/prompts/outreach.system",
            json={"current_text": "Prompt humano de outreach que ya no canta a robot y supera de sobra el minimo."},
        )
        reset = client.post("/api/nexus/prompts/outreach.system/reset")

    assert listing.status_code == 200
    assert any(item["key"] == "outreach.system" for item in listing.json()["prompts"])
    assert update.status_code == 200
    assert update.json()["prompt"]["is_overridden"] is True
    assert reset.status_code == 200
    assert reset.json()["prompt"]["is_overridden"] is False
