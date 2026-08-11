"""tests/unit/test_pepo_conversations_store.py

Tests unitarios para PepoConversationStore — historial de conversaciones de
PEPO (Nexus Desktop), SQLite local.
"""

from __future__ import annotations

from desktop.storage.conversations import PepoConversationStore


def _store(tmp_path) -> PepoConversationStore:
    return PepoConversationStore(tmp_path / "pepo_conversations.db")


def test_create_conversation_derives_title_from_first_message(tmp_path):
    store = _store(tmp_path)
    conv = store.create_conversation("Quiero prospectar peluquerias en Zaragoza")
    assert conv.id.startswith("pconv-")
    assert conv.title == "Quiero prospectar peluquerias en Zaragoza"
    assert conv.created_at == conv.updated_at


def test_create_conversation_truncates_long_title(tmp_path):
    store = _store(tmp_path)
    long_text = "palabra " * 30
    conv = store.create_conversation(long_text)
    assert len(conv.title) <= 61  # 60 + "…"
    assert conv.title.endswith("…")


def test_create_conversation_empty_message_falls_back_to_default_title(tmp_path):
    store = _store(tmp_path)
    conv = store.create_conversation("   ")
    assert conv.title == "Nueva conversación"


def test_get_conversation_returns_none_when_missing(tmp_path):
    store = _store(tmp_path)
    assert store.get_conversation("no-existe") is None


def test_append_turn_persists_both_messages_in_order(tmp_path):
    store = _store(tmp_path)
    conv = store.create_conversation("hola")
    store.append_turn(conv.id, user_message="hola", assistant_message="hola, ¿en qué ayudo?")
    store.append_turn(conv.id, user_message="una cosa mas", assistant_message="dime")

    messages = store.get_messages(conv.id)
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert [m.content for m in messages] == ["hola", "hola, ¿en qué ayudo?", "una cosa mas", "dime"]


def test_append_turn_updates_conversation_updated_at(tmp_path):
    store = _store(tmp_path)
    conv = store.create_conversation("hola")
    original_updated_at = conv.updated_at

    store.append_turn(conv.id, user_message="hola", assistant_message="hola")

    refreshed = store.get_conversation(conv.id)
    assert refreshed.updated_at >= original_updated_at


def test_list_conversations_orders_most_recently_updated_first(tmp_path):
    store = _store(tmp_path)
    first = store.create_conversation("primera conversacion")
    second = store.create_conversation("segunda conversacion")

    # Tocar la primera de nuevo — debe subir al principio del listado.
    store.append_turn(first.id, user_message="otra vez", assistant_message="ok")

    ids_in_order = [c.id for c in store.list_conversations()]
    assert ids_in_order[0] == first.id
    assert ids_in_order[1] == second.id


def test_list_conversations_respects_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.create_conversation(f"conversacion {i}")

    assert len(store.list_conversations(limit=2)) == 2
    assert len(store.list_conversations(limit=50)) == 5


def test_get_messages_empty_for_conversation_without_turns(tmp_path):
    store = _store(tmp_path)
    conv = store.create_conversation("hola")
    assert store.get_messages(conv.id) == []


def test_store_survives_reopening_same_db_path(tmp_path):
    """Persistencia real entre 'reinicios' — construir un segundo store
    sobre el mismo fichero debe ver los datos del primero."""
    db_path = tmp_path / "pepo_conversations.db"
    store1 = PepoConversationStore(db_path)
    conv = store1.create_conversation("mensaje persistente")
    store1.append_turn(conv.id, user_message="mensaje persistente", assistant_message="recibido")

    store2 = PepoConversationStore(db_path)
    reloaded = store2.get_conversation(conv.id)
    assert reloaded is not None
    assert reloaded.title == "mensaje persistente"
    assert len(store2.get_messages(conv.id)) == 2
