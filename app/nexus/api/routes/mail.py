"""Mail routes: estado de Thunderbird y mensajes prioritarios."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nexus.api.dependencies.auth import get_mail_manager
from nexus.mail import ThunderbirdMailManager

router = APIRouter()


@router.get("/mail/status")
def get_mail_status(mail: ThunderbirdMailManager = Depends(get_mail_manager)) -> dict:
    """Devuelve si Thunderbird esta configurado y que cuentas hay disponibles."""
    return mail.status()


@router.get("/mail/priority")
async def get_mail_priority(
    limit: int | None = None,
    mail: ThunderbirdMailManager = Depends(get_mail_manager),
) -> dict:
    """Devuelve los correos con mayor prioridad segun heuristica e IA."""
    return await mail.get_priority_messages(limit=limit)
