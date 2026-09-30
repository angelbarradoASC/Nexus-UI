"""Outlook routes: estado, login interactivo, mensajes prioritarios y respuesta."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_outlook_manager
from nexus.mail import OutlookAuthError, OutlookMailManager

router = APIRouter()


class _ReplyBody(BaseModel):
    message_id: str
    body: str


class _SendBody(BaseModel):
    to: str
    subject: str
    body: str


@router.get("/outlook/status")
def get_outlook_status(outlook: OutlookMailManager = Depends(get_outlook_manager)) -> dict:
    """Devuelve si Outlook esta autenticado y que cuenta esta activa."""
    return outlook.status()


@router.post("/outlook/login")
def outlook_login(outlook: OutlookMailManager = Depends(get_outlook_manager)) -> dict:
    """Lanza el flujo de login interactivo con Microsoft (abre el navegador)."""
    try:
        return outlook.start_interactive_login()
    except OutlookAuthError as exc:
        return {"status": "error", "reason": str(exc)}


@router.get("/outlook/priority")
async def get_outlook_priority(
    limit: int | None = None,
    outlook: OutlookMailManager = Depends(get_outlook_manager),
) -> dict:
    """Devuelve los correos de la bandeja de entrada con mayor prioridad."""
    return await outlook.get_priority_messages(limit=limit)


@router.post("/outlook/reply")
async def outlook_reply(
    body: _ReplyBody,
    outlook: OutlookMailManager = Depends(get_outlook_manager),
) -> dict:
    """Responde dentro del hilo real de un correo existente."""
    return await outlook.send_reply(body.message_id, body.body)


@router.post("/outlook/send")
async def outlook_send(
    body: _SendBody,
    outlook: OutlookMailManager = Depends(get_outlook_manager),
) -> dict:
    """Envia un correo nuevo (no una respuesta a un hilo existente)."""
    return await outlook.send_new(to=body.to, subject=body.subject, body=body.body)
