from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.llm_router import LLMResponse
from nexus.outreach.service import OutreachManager

ACCOUNT_KEY = "sls_assetsconsultores"
ACCOUNT_EMAIL = "vicentearaizeta@sls.assetsconsultores.es"


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


class _FakeReplyIMAP:
    """Fake de IMAPMailboxMonitor.find_replies — usado para probar
    check_replies() sin tocar IMAP real. `replies` mapea email -> ISO
    timestamp de la respuesta fake."""

    def __init__(self, replies: dict[str, str] | None = None):
        self.replies = replies or {}
        self.calls: list[dict] = []

    def find_replies(self, *, from_addresses, since):
        self.calls.append({"from_addresses": list(from_addresses), "since": since})
        return {addr: ts for addr, ts in self.replies.items() if addr in from_addresses}


class _FakeCredentialStore:
    """Sustituye a CredentialStore (data/credentials.enc) en los tests — sin
    tocar disco ni cifrado real. Pre-sembrado con la cuenta real usada en
    la vía IA/OT (vicentearaizeta@sls.assetsconsultores.es)."""

    def __init__(self, accounts: dict[str, dict] | None = None):
        self._accounts = {
            f"outreach_smtp:{ACCOUNT_KEY}": {
                "user": ACCOUNT_EMAIL,
                "password": "x",
                "host": "smtp.migadu.com",
                "port": 465,
                "email": ACCOUNT_EMAIL,
            },
            f"outreach_imap:{ACCOUNT_KEY}": {
                "user": ACCOUNT_EMAIL,
                "password": "x",
                "host": "imap.migadu.com",
                "port": 993,
                "email": ACCOUNT_EMAIL,
            },
            **(accounts or {}),
        }

    def get(self, key: str):
        return self._accounts.get(key)

    def list_hosts(self) -> list[str]:
        return list(self._accounts.keys())


@pytest.fixture
def outreach_cfg(tmp_path: Path):
    return type(
        "OutreachCfg",
        (),
        {
            "outreach_enabled": False,
            "outreach_sender_name": "Vicente Araizeta",
            "outreach_imap_host": "imap.migadu.com",
            "outreach_imap_port": 993,
            "outreach_imap_user": ACCOUNT_EMAIL,
            "outreach_imap_password": "",
            "outreach_daily_cap_default": 20,
            "outreach_followup_delays_days": "4,9",
            "outreach_data_dir": str(tmp_path / "outreach-data"),
        },
    )()


def _manager(
    outreach_cfg,
    *,
    llm_router=None,
    smtp: _FakeSMTP | None = None,
    credentials: _FakeCredentialStore | None = None,
    reply_imap: _FakeReplyIMAP | None = None,
) -> OutreachManager:
    smtp = smtp or _FakeSMTP()
    return OutreachManager(
        cfg=outreach_cfg,
        llm_router=llm_router,
        credential_store=credentials or _FakeCredentialStore(),
        imap_monitor=_FakeIMAP(),
        transport_factory=lambda **_kwargs: smtp,
        imap_monitor_factory=lambda **_kwargs: (reply_imap or _FakeReplyIMAP()),
    )


@pytest.mark.asyncio
async def test_outreach_status_reports_known_accounts_and_counters(outreach_cfg):
    manager = _manager(outreach_cfg, smtp=_FakeSMTP(configured=False))

    status = await manager.status()

    assert status["status"] == "success"
    assert status["accounts"][ACCOUNT_KEY]["email"] == ACCOUNT_EMAIL
    assert status["daily_cap_default"] == 20
    assert status["sent_today"] == 0


@pytest.mark.asyncio
async def test_outreach_launch_campaign_requires_outreach_account(outreach_cfg):
    manager = _manager(outreach_cfg)

    with pytest.raises(ValueError, match="outreach_account"):
        await manager.launch_campaign(
            {
                "campaign_name": "Sin cuenta",
                "proposition": "x",
                "csv_text": "email,first_name,company\nalice@example.com,Alice,Example",
                "dry_run": True,
            }
        )


@pytest.mark.asyncio
async def test_outreach_launch_campaign_rejects_unknown_account(outreach_cfg):
    manager = _manager(outreach_cfg)

    with pytest.raises(ValueError, match="No hay credenciales"):
        await manager.launch_campaign(
            {
                "campaign_name": "Cuenta inventada",
                "proposition": "x",
                "outreach_account": "no_existe",
                "csv_text": "email,first_name,company\nalice@example.com,Alice,Example",
                "dry_run": True,
            }
        )


def _multi_account_manager(outreach_cfg, *, healthy: dict[str, bool]) -> OutreachManager:
    """Manager con varias cuentas SMTP fake, cada una con su propia salud —
    _manager() de arriba usa UN unico fake compartido por account_key (sirve
    para una sola cuenta), aqui se necesita diferenciar por cuenta para
    probar pick_account() con un pool real de varias."""
    credentials = _FakeCredentialStore({
        f"outreach_smtp:{key}": {
            "user": f"{key}@example.com", "password": "x", "host": "h", "port": 465, "email": f"{key}@example.com",
        }
        for key in healthy
    })
    smtp_by_username = {f"{key}@example.com": _FakeSMTP(configured=is_healthy) for key, is_healthy in healthy.items()}

    def factory(*, host, port, username, password):
        return smtp_by_username[username]

    return OutreachManager(
        cfg=outreach_cfg,
        llm_router=None,
        credential_store=credentials,
        imap_monitor=_FakeIMAP(),
        transport_factory=factory,
        imap_monitor_factory=lambda **_kwargs: _FakeReplyIMAP(),
    )


@pytest.mark.asyncio
async def test_pick_account_round_robins_between_healthy_candidates(outreach_cfg):
    manager = _multi_account_manager(outreach_cfg, healthy={"automato": True, "sls_assetsconsultores": True})

    picks = [await manager.pick_account(["automato", "sls_assetsconsultores"]) for _ in range(4)]

    # sorted(["automato", "sls_assetsconsultores"]) — orden alfabetico, round-robin
    assert picks == ["automato", "sls_assetsconsultores", "automato", "sls_assetsconsultores"]


@pytest.mark.asyncio
async def test_pick_account_skips_candidate_that_fails_healthcheck(outreach_cfg):
    manager = _multi_account_manager(outreach_cfg, healthy={"automato": False, "sls_assetsconsultores": True})

    picks = [await manager.pick_account(["automato", "sls_assetsconsultores"]) for _ in range(3)]

    assert picks == ["sls_assetsconsultores"] * 3


@pytest.mark.asyncio
async def test_pick_account_raises_when_no_candidate_is_healthy(outreach_cfg):
    manager = _multi_account_manager(outreach_cfg, healthy={"automato": False})

    with pytest.raises(ValueError, match="sana"):
        await manager.pick_account(["automato"])


@pytest.mark.asyncio
async def test_pick_account_single_candidate_behaves_like_before(outreach_cfg):
    """Con un solo candidato (el caso de hoy, sin pool) se comporta igual
    que el outreach_account unico de siempre: lo verifica y lo devuelve."""
    manager = _manager(outreach_cfg)

    picked = await manager.pick_account([ACCOUNT_KEY])

    assert picked == ACCOUNT_KEY


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
    manager = _manager(outreach_cfg, llm_router=llm_router)

    response = await manager.launch_campaign(
        {
            "campaign_name": "Acme Q3",
            "proposition": "servicios gestionados y ciberseguridad",
            "cta": "Si te encaja, coordinamos una llamada breve.",
            "outreach_account": ACCOUNT_KEY,
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
    manager = _manager(outreach_cfg, llm_router=llm_router, smtp=smtp)

    created = await manager.launch_campaign(
        {
            "campaign_name": "Live demo",
            "proposition": "monitorizacion y operaciones",
            "outreach_account": ACCOUNT_KEY,
            "csv_text": "email,first_name,company\nalice@example.com,Alice,Example",
            "dry_run": False,
        }
    )

    assert created["status"] == "accepted"
    assert created["events"][0]["event_type"] == "email_sent"
    assert created["events"][0]["delivery_status"] == "sent"
    assert len(smtp.sent_messages) == 1
    assert smtp.sent_messages[0]["From"] == f"Vicente Araizeta <{ACCOUNT_EMAIL}>"


async def _launch_real_campaign(outreach_cfg, *, smtp: _FakeSMTP, email: str = "prospecto@example.com") -> dict:
    manager = _manager(outreach_cfg, smtp=smtp)
    return await manager.launch_campaign({
        "campaign_name": "Reply test",
        "proposition": "x",
        "outreach_account": ACCOUNT_KEY,
        "csv_text": f"email,first_name,company\n{email},Prospecto,Ejemplo",
        "dry_run": False,
    })


@pytest.mark.asyncio
async def test_check_replies_marks_prospect_replied_and_stops_followups(outreach_cfg):
    """Pedido explicito del usuario: monitorizar si hay respuesta real a
    los correos enviados. Una respuesta real (fecha posterior al ultimo
    contacto) marca el prospecto como 'replied' y para sus follow-ups —
    mismo mecanismo que 'completed' (next_due_at a None)."""
    smtp = _FakeSMTP()
    created = await _launch_real_campaign(outreach_cfg, smtp=smtp)
    sent_at = datetime.fromisoformat(created["events"][0]["timestamp"])
    reply_at = (sent_at + timedelta(minutes=5)).isoformat()

    reply_imap = _FakeReplyIMAP(replies={"prospecto@example.com": reply_at})
    manager = _manager(outreach_cfg, smtp=smtp, reply_imap=reply_imap)

    events = await manager.check_replies(ACCOUNT_KEY)

    assert len(events) == 1
    assert events[0]["recipient_email"] == "prospecto@example.com"
    assert events[0]["event_type"] == "reply_detected"
    campaigns = await manager._repository.load_campaigns()
    prospect = campaigns[0]["prospects"][0]
    assert prospect["status"] == "replied"
    assert prospect["next_due_at"] is None


@pytest.mark.asyncio
async def test_check_replies_ignores_message_older_than_last_contact(outreach_cfg):
    """Un mensaje encontrado con fecha ANTERIOR (o igual) al ultimo contacto
    no es una respuesta real — evita falsos positivos de correo antiguo en
    la bandeja."""
    smtp = _FakeSMTP()
    created = await _launch_real_campaign(outreach_cfg, smtp=smtp)
    sent_at = datetime.fromisoformat(created["events"][0]["timestamp"])
    old_message_at = (sent_at - timedelta(days=10)).isoformat()

    reply_imap = _FakeReplyIMAP(replies={"prospecto@example.com": old_message_at})
    manager = _manager(outreach_cfg, smtp=smtp, reply_imap=reply_imap)

    events = await manager.check_replies(ACCOUNT_KEY)

    assert events == []
    campaigns = await manager._repository.load_campaigns()
    assert campaigns[0]["prospects"][0]["status"] == "waiting_followup"


@pytest.mark.asyncio
async def test_check_replies_skips_prospects_already_completed(outreach_cfg):
    smtp = _FakeSMTP()
    created = await _launch_real_campaign(outreach_cfg, smtp=smtp)
    manager = _manager(outreach_cfg, smtp=smtp)
    campaigns = await manager._repository.load_campaigns()
    campaigns[0]["prospects"][0]["status"] = "completed"
    await manager._repository.save_campaigns(campaigns)

    reply_imap = _FakeReplyIMAP(replies={"prospecto@example.com": datetime.now().isoformat()})
    manager2 = _manager(outreach_cfg, smtp=smtp, reply_imap=reply_imap)

    events = await manager2.check_replies(ACCOUNT_KEY)

    assert events == []
    assert reply_imap.calls == []  # ni siquiera se llega a preguntar al IMAP


@pytest.mark.asyncio
async def test_check_replies_returns_empty_without_imap_credentials_for_account(outreach_cfg):
    manager = _manager(outreach_cfg)

    events = await manager.check_replies("cuenta_sin_credenciales")

    assert events == []
