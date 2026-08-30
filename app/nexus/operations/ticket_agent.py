"""
app/nexus/operations/ticket_agent.py
-------------------------------------
TicketAgent — gate de confirmacion humana antes de crear un ticket real en
Assets desde el chat de PEPO.

Bug real que motiva esto: el clasificador de intencion (DesktopSkillRouter)
resolvio una pregunta meta ("por que da timeout?") como
assets.crear_ticket_operador, y como _handle_assets_ticket_chat llamaba a
create_ticket_from_message() directamente y sin pedir nada, PEPO creo un
ticket real que nadie pidio. La clasificacion de intencion nunca va a ser
perfecta — el freno de verdad tiene que ser la confirmacion humana antes de
escribir en un sistema externo, igual que ya hace MouseAgent con la
velocidad del raton o SystemTaskAgent con un script.

enrich_ticket_from_message() (composicion, solo lectura, usa LLM) ya estaba
separado de create_ticket() (la escritura real) en AssetsOperationsService
— este agente solo añade el paso de confirmacion entre los dos que faltaba.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PendingTicket:
    message: str
    ticket_payload: dict[str, Any]
    actor: str = "operator"
    extracted: dict[str, Any] = field(default_factory=dict)


class TicketAgent:
    """Confirmacion en dos pasos para assets.crear_ticket_operador / jira.crear_ticket
    via chat. No persiste entre reinicios (a diferencia de los agentes de
    desktop/local_agents/*) porque el ciclo propose->confirm es de un solo
    turno de chat, no algo que sobreviva razonablemente a un reinicio del
    proceso — decision deliberada para no anadir una dependencia de store
    a un runtime que tambien corre sin desktop."""

    persistence_key = "ticket"

    def __init__(self, operations) -> None:
        self._operations = operations
        self._pending: dict[str, PendingTicket] = {}

    async def propose(
        self,
        context_id: str,
        message: str,
        *,
        actor: str = "operator",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enriched = await self._operations.enrich_ticket_from_message(
            message, source="codex", trigger_kind="operator", context=context or {},
        )
        ticket_payload = enriched["ticket_payload"]
        self._pending[context_id] = PendingTicket(
            message=message, ticket_payload=ticket_payload, actor=actor,
            extracted=enriched.get("extracted", {}),
        )
        return {"kind": "ticket_proposal", "ticket_payload": ticket_payload}

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    async def list_pending(self) -> list[dict[str, Any]]:
        return [
            {
                "context_id": context_id,
                "agent_id": "ticket",
                "kind": "ticket_proposal",
                "summary": pending.ticket_payload.get("title") or pending.message[:160],
            }
            for context_id, pending in self._pending.items()
        ]

    def pending_ticket_payload(self, context_id: str) -> dict[str, Any] | None:
        pending = self._pending.get(context_id)
        return pending.ticket_payload if pending else None

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any] | None:
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return None

        try:
            created = await self._operations.create_ticket(pending.ticket_payload)
        except Exception as exc:
            return {
                "task_id": None, "task_title": None,
                "ticket_payload": pending.ticket_payload, "error": str(exc),
            }

        task = created.get("task", {})
        return {
            "task_id": task.get("id"),
            "task_title": task.get("title"),
            "ticket_payload": pending.ticket_payload,
            "error": None,
        }
