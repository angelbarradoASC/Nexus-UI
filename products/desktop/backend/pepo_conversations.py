"""Historial de conversaciones de PEPO — persistido en SQLite, Desktop-only.

Deliberadamente NO vive en `app/nexus/api/routes/pepo.py` (compartido con
Web, depende de `CaseLogStore`, un concepto distinto) — el almacenamiento
aquí es SQLite/Desktop-only, acoplarlo al router compartido reintroduciría
justo la mezcla de responsabilidades que la refactorización de deduplicación
de Nexus Desktop dejó separada.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from desktop.config import DesktopSettings
from desktop.storage.conversations import PepoConversationStore
from products.desktop.backend.dependencies import get_desktop_settings

router = APIRouter()


def get_pepo_conversation_store(settings: DesktopSettings = Depends(get_desktop_settings)) -> PepoConversationStore:
    return PepoConversationStore(settings.pepo_conversations_db_path)


class _NewConversationBody(BaseModel):
    first_message: str


class _AppendTurnBody(BaseModel):
    user_message: str
    assistant_message: str


@router.get("/api/desktop/pepo/conversations")
async def list_conversations(store: PepoConversationStore = Depends(get_pepo_conversation_store)):
    conversations = store.list_conversations()
    return {"available": True, "conversations": [c.to_dict() for c in conversations]}


@router.post("/api/desktop/pepo/conversations")
async def create_conversation(
    body: _NewConversationBody,
    store: PepoConversationStore = Depends(get_pepo_conversation_store),
):
    conversation = store.create_conversation(body.first_message)
    return {"available": True, "conversation": conversation.to_dict()}


@router.get("/api/desktop/pepo/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    store: PepoConversationStore = Depends(get_pepo_conversation_store),
):
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")
    messages = store.get_messages(conversation_id)
    return {
        "available": True,
        "conversation": conversation.to_dict(),
        "messages": [m.to_dict() for m in messages],
    }


@router.post("/api/desktop/pepo/conversations/{conversation_id}/messages")
async def append_conversation_turn(
    conversation_id: str,
    body: _AppendTurnBody,
    store: PepoConversationStore = Depends(get_pepo_conversation_store),
):
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")
    store.append_turn(conversation_id, user_message=body.user_message, assistant_message=body.assistant_message)
    return {"available": True, "status": "saved"}


@router.delete("/api/desktop/pepo/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    store: PepoConversationStore = Depends(get_pepo_conversation_store),
):
    deleted = store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada")
    return {"available": True, "status": "deleted"}
