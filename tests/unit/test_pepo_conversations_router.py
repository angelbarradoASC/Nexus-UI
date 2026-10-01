"""tests/unit/test_pepo_conversations_router.py

Boton "eliminar conversacion" en el historial de PEPO — pedido explicito
del usuario tras ver que el historial solo permitia crear/leer, nunca
borrar. Cubre el endpoint DELETE de forma aislada (sin arrancar la app
Desktop completa: solo el router + un store real en tmp_path).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from desktop.storage.conversations import PepoConversationStore
from products.desktop.backend import pepo_conversations
from products.desktop.backend.pepo_conversations import get_pepo_conversation_store


def _client(tmp_path) -> tuple[TestClient, PepoConversationStore]:
    store = PepoConversationStore(tmp_path / "pepo_conversations.db")
    app = FastAPI()
    app.include_router(pepo_conversations.router)
    app.dependency_overrides[get_pepo_conversation_store] = lambda: store
    return TestClient(app), store


def test_delete_existing_conversation_returns_ok_and_removes_it(tmp_path):
    client, store = _client(tmp_path)
    conv = store.create_conversation("hola")

    response = client.delete(f"/api/desktop/pepo/conversations/{conv.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert store.get_conversation(conv.id) is None


def test_delete_missing_conversation_returns_404(tmp_path):
    client, _store = _client(tmp_path)

    response = client.delete("/api/desktop/pepo/conversations/no-existe")

    assert response.status_code == 404


def test_deleted_conversation_no_longer_appears_in_list(tmp_path):
    client, store = _client(tmp_path)
    keep = store.create_conversation("se queda")
    doomed = store.create_conversation("se borra")

    client.delete(f"/api/desktop/pepo/conversations/{doomed.id}")
    listing = client.get("/api/desktop/pepo/conversations").json()

    ids = [c["id"] for c in listing["conversations"]]
    assert ids == [keep.id]


def test_proactive_conversation_has_pepo_message_without_user_turn(tmp_path):
    """OutlookWatcherAgent (y cualquier otro agente de fondo) usa este
    endpoint para que PEPO hable primero — pedido explicito del usuario:
    los asistentes deben poder tomar la iniciativa."""
    client, store = _client(tmp_path)

    response = client.post(
        "/api/desktop/pepo/conversations/proactive",
        json={"first_message": "Te ha llegado un correo importante de Laura."},
    )

    assert response.status_code == 200
    conversation_id = response.json()["conversation"]["id"]
    messages = store.get_messages(conversation_id)
    assert [m.role for m in messages] == ["assistant"]
    assert messages[0].content == "Te ha llegado un correo importante de Laura."
