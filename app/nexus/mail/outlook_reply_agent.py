"""Confirmacion en dos pasos para responder un correo real de Outlook.

Mismo contrato minimo que los demas agentes locales con confirmacion
(mouse_agent, system_task_agent, remote_ops_agent, mcp_agent, ticket_agent
— ver NexusCoordinator.list_pending_actions/_find_pending_agent):
has_pending(context_id) / confirm(context_id, user_reply) / cancel(context_id)
/ list_pending(). Se pluguea en la misma cola "Agentes" sin duplicar logica
de confirmacion — un correo real a un tercero nunca se envia sin que el
usuario diga que si explicitamente (PermissionLevel.OPERATE).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class _PendingReply:
    message_id: str
    subject: str
    recipient: str
    draft_body: str
    created_at: str


class OutlookReplyAgent:
    def __init__(self, outlook) -> None:
        self._outlook = outlook
        self._pending: dict[str, _PendingReply] = {}

    def propose(
        self,
        context_id: str,
        *,
        message_id: str,
        subject: str,
        recipient: str,
        draft_body: str,
    ) -> None:
        self._pending[context_id] = _PendingReply(
            message_id=message_id,
            subject=subject,
            recipient=recipient,
            draft_body=draft_body,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    def peek(self, context_id: str) -> _PendingReply | None:
        return self._pending.get(context_id)

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any]:
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return {"status": "not_found"}
        result = await self._outlook.send_reply(pending.message_id, pending.draft_body)
        return {"status": result.get("status", "error"), "recipient": pending.recipient}

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)

    async def list_pending(self) -> list[dict[str, Any]]:
        return [
            {
                "context_id": context_id,
                "agent_id": "mail.outlook_reply",
                "kind": "outlook_reply",
                "summary": f"Responder a {pending.recipient}: \"{pending.subject}\"",
            }
            for context_id, pending in self._pending.items()
        ]
