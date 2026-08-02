"""Teams routes: estado, login interactivo, mensajes prioritarios y respuesta."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_teams_manager
from nexus.teams import TeamsChatManager, TeamsAuthError

router = APIRouter()


class _SendBody(BaseModel):
    chat_id: str
    text: str


class _RespondBody(BaseModel):
    chat_id: str
    message_text: str
    sender_name: str = ""


@router.get("/teams/status")
def get_teams_status(teams: TeamsChatManager = Depends(get_teams_manager)) -> dict:
    """Devuelve si Teams esta autenticado y que cuenta esta activa."""
    return teams.status()


@router.post("/teams/login")
def teams_login(teams: TeamsChatManager = Depends(get_teams_manager)) -> dict:
    """Lanza el flujo de login interactivo con Microsoft (abre el navegador)."""
    try:
        return teams.start_interactive_login()
    except TeamsAuthError as exc:
        return {"status": "error", "reason": str(exc)}


@router.get("/teams/priority")
async def get_teams_priority(
    limit: int | None = None,
    teams: TeamsChatManager = Depends(get_teams_manager),
) -> dict:
    """Devuelve los mensajes de Teams con mayor prioridad."""
    return await teams.get_priority_messages(limit=limit)


@router.post("/teams/send")
async def send_teams_message(
    body: _SendBody,
    teams: TeamsChatManager = Depends(get_teams_manager),
) -> dict:
    """Envia un mensaje de texto a un chat de Teams."""
    return await teams.send_message(body.chat_id, body.text)


@router.post("/teams/respond")
async def respond_teams_message(
    body: _RespondBody,
    teams: TeamsChatManager = Depends(get_teams_manager),
) -> dict:
    """Genera y envia una respuesta automatica de PEPO a un mensaje de Teams."""
    return await teams.respond_to_message(
        body.chat_id,
        body.message_text,
        sender_name=body.sender_name,
    )
