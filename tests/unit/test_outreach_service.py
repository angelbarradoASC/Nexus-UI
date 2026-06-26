from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.llm_router import LLMResponse
from nexus.outreach.service import OutreachManager


class _FakeSMTP:
    def __init__(self, configured: bool = True):
        self._configured = configured
        self.sent_messages = []

    def configured(self) -> bool:
        return self._configured

    def send(self, message):
        self.sent_messages.append(message)
        return {"status": "sent"}

    def healthcheck(self):
        return {"configured": self._configured, "status": "up" if self._configured else "not_configured"}


class _FakeIMAP:
    def __init__(self, configured: bool = True):
        self._configured = configured

    def configured(self) -> bool:
        return self._configured

    def healthcheck(self):
        return {"configured": self._configured, "status": "up" if self._configured else "not_configured", "unread_count": 2}


@pytest.fixture
def outreach_cfg(tmp_path: Path):
    return type(
        "OutreachCfg",
        (),
        {
            "outreach_enabled": False,
            "outreach_email_address": "vicentearaizeta@sls.assetsconsultores.es",
            "outreach_sender_name": "Vicente Araizeta",
            "outreach_smtp_host": "smtp.migadu.com",
            "outreach_smtp_port": 465,
            "outreach_smtp_user": "vicentearaizeta@sls.assetsconsultores.es",
            "outreach_smtp_password": "",
            "outreach_imap_host": "imap.migadu.com",
            "outreach_imap_port": 993,
            "outreach_imap_user": "vicentearaizeta@sls.assetsconsultores.es",
            "outreach_imap_password": "",
            "outreach_daily_cap_default": 20,
            "outreach_followup_delays_days": "4,9",
            "outreach_data_dir": str(tmp_path / "outreach-data"),
        },
    )()


@pytest.mark.asyncio
async def test_outreach_status_reports_mailbox_and_counters(outreach_cfg):
    manager = OutreachManager(
        cfg=outreach_cfg,
        llm_router=None,
        smtp_transport=_FakeSMTP(configured=False),
        imap_monitor=_FakeIMAP(configured=False),
    )

    status = await manager.status()

    assert status["status"] == "success"
    assert status["account"]["email"] == "vicentearaizeta@sls.assetsconsultores.es"
    assert status["daily_cap_default"] == 20
    assert status["sent_today"] == 0


@pytest.mark.asyncio
async def test_outreach_launch_campaign_parses_csv_and_previews_messages(outreach_cfg):
    llm_router = MagicMock()
    llm_router.call = AsyncMock(
        return_value=LLMResponse(
            content='{"subject":"Idea para Acme","body":"Hola Laura,\\n\\nQueria compartirte una idea para Acme.\\n\\nUn saludo."}',
            level_used=1,
            model_used="gemini-3.5-flash",
            nivel_name="L1-Cloud",
            latency_ms=120,
        )
    )
    manager = OutreachManager(
        cfg=outreach_cfg,
        llm_router=llm_router,
        smtp_transport=_FakeSMTP(),
        imap_monitor=_FakeIMAP(),
    )

    response = await manager.launch_campaign(
        {
            "campaign_name": "Acme Q3",
            "proposition": "servicios gestionados y ciberseguridad",
            "cta": "Si te encaja, coordinamos una llamada breve.",
            "csv_text": "email,first_name,company,job_title,company_domain,notes\nlaura@acme.com,Laura,Acme,CIO,acme.com,Empresa con varias sedes",
            "dry_run": True,
        }
    )

    assert response["status"] == "accepted"
    assert response["campaign_id"].startswith("out-")
    assert response["total_prospects"] == 1
    assert response["executed_count"] == 1
    assert response["events"][0]["event_type"] == "email_preview"


@pytest.mark.asyncio
async def test_outreach_run_campaign_sends_live_when_enabled(outreach_cfg):
    llm_router = MagicMock()
    llm_router.call = AsyncMock(
        return_value=LLMResponse(
            content='{"subject":"Seguimiento","body":"Hola,\\n\\nRetomo este tema.\\n\\nGracias."}',
            level_used=1,
            model_used="gemini-3.5-flash",
            nivel_name="L1-Cloud",
            latency_ms=110,
        )
    )
    smtp = _FakeSMTP()
    manager = OutreachManager(
        cfg=outreach_cfg,
        llm_router=llm_router,
        smtp_transport=smtp,
        imap_monitor=_FakeIMAP(),
    )

    created = await manager.launch_campaign(
        {
            "campaign_name": "Live demo",
            "proposition": "monitorizacion y operaciones",
            "csv_text": "email,first_name,company\nalice@example.com,Alice,Example",
            "dry_run": False,
        }
    )

    assert created["status"] == "accepted"
    assert created["events"][0]["event_type"] == "email_sent"
    assert created["events"][0]["delivery_status"] == "sent"
    assert len(smtp.sent_messages) == 1
