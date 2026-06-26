from __future__ import annotations

from pathlib import Path

import pytest

from nexus.crm.service import CRMBridgeService


class _FakeConnector:
    def __init__(self):
        self.created = []
        self.patched = []
        self.noted = []
        self.found_company = None

    async def status(self):
        return {
            "provider": "assets-web-api",
            "configured": True,
            "status": "up",
            "base_url": "http://127.0.0.1:8000",
            "username": "admin",
        }

    async def find_company_by_domain(self, domain: str):
        return self.found_company

    async def create_company(self, payload):
        self.created.append(payload)
        return {"company": {"id": 12, "name": payload["name"], "domain": payload["domain"]}}

    async def update_company_pipeline(self, company_id: int, payload):
        self.patched.append((company_id, payload))
        return {"company": {"id": company_id}}

    async def add_pipeline_note(self, company_id: int, payload):
        self.noted.append((company_id, payload))
        return {"note": {"id": 1}}


class _Repo:
    def __init__(self, campaign):
        self._campaigns = [campaign]

    async def load_campaigns(self):
        return self._campaigns

    async def save_campaigns(self, campaigns):
        self._campaigns = campaigns


@pytest.mark.asyncio
async def test_crm_bridge_status_and_sync_dry_run(tmp_path: Path):
    campaign = {
        "campaign_id": "out-001",
        "campaign_name": "Primeros tres",
        "proposition": "servicios gestionados",
        "cta": "Hablamos esta semana",
        "prospects": [
            {
                "prospect_id": "pros-001",
                "email": "alice@example.com",
                "first_name": "Alice",
                "company": "Example",
                "job_title": "CIO",
                "company_domain": "example.com",
                "notes": "Empresa objetivo",
                "history": [],
            }
        ],
    }
    cfg = type(
        "Cfg",
        (),
        {
            "outreach_data_dir": str(tmp_path / "outreach"),
            "assets_crm_base_url": "http://127.0.0.1:8000",
            "assets_crm_username": "admin",
            "assets_crm_password": "secret",
        },
    )()

    service = CRMBridgeService(cfg=cfg, repository=_Repo(campaign), connector=_FakeConnector())

    status = await service.status()
    sync = await service.sync_campaign("out-001", dry_run=True, limit=3)

    assert status["provider"] == "assets-web-api"
    assert status["pending_prospects"] == 1
    assert sync["status"] == "accepted"
    assert sync["synced_count"] == 1
    assert sync["results"][0]["status"] == "preview"


@pytest.mark.asyncio
async def test_crm_bridge_sync_live_marks_prospect(tmp_path: Path):
    campaign = {
        "campaign_id": "out-001",
        "campaign_name": "Primeros tres",
        "proposition": "servicios gestionados",
        "cta": "Hablamos esta semana",
        "prospects": [
            {
                "prospect_id": "pros-001",
                "email": "alice@example.com",
                "first_name": "Alice",
                "company": "Example",
                "job_title": "CIO",
                "company_domain": "example.com",
                "notes": "",
                "history": [],
            }
        ],
    }
    cfg = type(
        "Cfg",
        (),
        {
            "outreach_data_dir": str(tmp_path / "outreach"),
            "assets_crm_base_url": "http://127.0.0.1:8000",
            "assets_crm_username": "admin",
            "assets_crm_password": "secret",
        },
    )()
    connector = _FakeConnector()
    repo = _Repo(campaign)
    service = CRMBridgeService(cfg=cfg, repository=repo, connector=connector)

    sync = await service.sync_campaign("out-001", dry_run=False, limit=3)

    assert sync["status"] == "accepted"
    assert sync["results"][0]["company_id"] == 12
    assert connector.created[0]["domain"] == "example.com"
    assert repo._campaigns[0]["prospects"][0]["crm_sync"]["company_id"] == 12


@pytest.mark.asyncio
async def test_ingest_inbound_mail_dry_run_builds_preview(tmp_path: Path):
    cfg = type(
        "Cfg",
        (),
        {
            "outreach_data_dir": str(tmp_path / "outreach"),
            "assets_crm_base_url": "http://127.0.0.1:8000",
            "assets_crm_username": "admin",
            "assets_crm_password": "secret",
        },
    )()
    connector = _FakeConnector()
    service = CRMBridgeService(cfg=cfg, repository=_Repo({"campaign_id": "noop", "prospects": []}), connector=connector)

    result = await service.ingest_inbound_mail(
        {
            "sender_name": "Karim Mribti",
            "sender_email": "karim.mribti@cbl-logistica.com",
            "subject": "Re: Una idea para CBL Logística",
            "preview": "Puede tener sentido hablarlo la semana que viene.",
            "classification_hint": "positive_reply",
        },
        dry_run=True,
    )

    assert result["status"] == "preview"
    assert result["domain"] == "cbl-logistica.com"
    assert result["pipeline_payload"]["pipeline_stage"] == "meeting"
    assert result["note_payload"]["note_type"] == "email"


@pytest.mark.asyncio
async def test_ingest_inbound_mail_live_reuses_company_and_writes_note(tmp_path: Path):
    cfg = type(
        "Cfg",
        (),
        {
            "outreach_data_dir": str(tmp_path / "outreach"),
            "assets_crm_base_url": "http://127.0.0.1:8000",
            "assets_crm_username": "admin",
            "assets_crm_password": "secret",
        },
    )()
    connector = _FakeConnector()
    connector.found_company = {"id": 99, "name": "CBL Logística Madrid", "domain": "cbl-logistica.com"}
    service = CRMBridgeService(cfg=cfg, repository=_Repo({"campaign_id": "noop", "prospects": []}), connector=connector)

    result = await service.ingest_inbound_mail(
        {
            "sender_name": "Karim Mribti",
            "sender_email": "karim.mribti@cbl-logistica.com",
            "subject": "Re: Una idea para CBL Logística",
            "preview": "Puede tener sentido hablarlo la semana que viene.",
            "classification_hint": "positive_reply",
        },
        dry_run=False,
    )

    assert result["status"] == "accepted"
    assert result["company_id"] == 99
    assert result["created_company"] is False
    assert connector.patched[0][0] == 99
    assert connector.patched[0][1]["pipeline_stage"] == "meeting"
    assert connector.noted[0][0] == 99
    assert "Correo entrante procesado por Nexus" in connector.noted[0][1]["content"]


@pytest.mark.asyncio
async def test_ingest_inbound_mail_ignores_internal_domains(tmp_path: Path):
    cfg = type(
        "Cfg",
        (),
        {
            "outreach_data_dir": str(tmp_path / "outreach"),
            "assets_crm_base_url": "http://127.0.0.1:8000",
            "assets_crm_username": "admin",
            "assets_crm_password": "secret",
        },
    )()
    connector = _FakeConnector()
    service = CRMBridgeService(cfg=cfg, repository=_Repo({"campaign_id": "noop", "prospects": []}), connector=connector)

    result = await service.ingest_inbound_mail(
        {
            "sender_email": "angel.barrado@assetsconsultores.es",
            "subject": "Interno",
            "preview": "Mensaje interno",
        },
        dry_run=False,
    )

    assert result["status"] == "ignored"
    assert connector.patched == []
    assert connector.noted == []
