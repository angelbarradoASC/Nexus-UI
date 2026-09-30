"""tests/unit/test_outlook_reply_agent.py

OutlookReplyAgent — confirmacion en dos pasos antes de enviar un correo
real a un tercero (PermissionLevel.OPERATE). Nunca se envia sin que
confirm() se llame explicitamente.
"""

from __future__ import annotations

import pytest


class _FakeOutlook:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_reply(self, message_id: str, body: str) -> dict:
        self.sent.append((message_id, body))
        return {"status": "success"}


def _agent():
    from nexus.mail.outlook_reply_agent import OutlookReplyAgent

    outlook = _FakeOutlook()
    return OutlookReplyAgent(outlook), outlook


def test_propose_creates_pending_but_never_sends():
    agent, outlook = _agent()

    agent.propose("ctx-1", message_id="msg-1", subject="Hola", recipient="laura@example.com", draft_body="Texto")

    assert agent.has_pending("ctx-1") is True
    assert outlook.sent == []


@pytest.mark.asyncio
async def test_confirm_sends_and_clears_pending():
    agent, outlook = _agent()
    agent.propose("ctx-1", message_id="msg-1", subject="Hola", recipient="laura@example.com", draft_body="Texto real")

    result = await agent.confirm("ctx-1")

    assert result["status"] == "success"
    assert outlook.sent == [("msg-1", "Texto real")]
    assert agent.has_pending("ctx-1") is False


@pytest.mark.asyncio
async def test_confirm_without_pending_returns_not_found():
    agent, outlook = _agent()

    result = await agent.confirm("ctx-nope")

    assert result == {"status": "not_found"}
    assert outlook.sent == []


def test_cancel_clears_pending_without_sending():
    agent, outlook = _agent()
    agent.propose("ctx-1", message_id="msg-1", subject="Hola", recipient="laura@example.com", draft_body="Texto")

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert outlook.sent == []


@pytest.mark.asyncio
async def test_list_pending_summarizes_recipient_and_subject():
    agent, _outlook = _agent()
    agent.propose("ctx-1", message_id="msg-1", subject="Propuesta", recipient="laura@example.com", draft_body="Texto")

    pending = await agent.list_pending()

    assert len(pending) == 1
    assert pending[0]["agent_id"] == "mail.outlook_reply"
    assert "laura@example.com" in pending[0]["summary"]
    assert "Propuesta" in pending[0]["summary"]
