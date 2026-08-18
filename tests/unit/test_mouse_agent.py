"""tests/unit/test_mouse_agent.py

Tests unitarios para MouseAgent — cambio de velocidad del ratón con
confirmación en dos pasos, y su persistencia en DesktopPendingActionStore
para sobrevivir un reinicio del proceso.
"""

from __future__ import annotations

import pytest

from desktop.local_agents.mouse_agent import MouseAgent
from desktop.storage.pending_actions import DesktopPendingActionStore


def _store(tmp_path) -> DesktopPendingActionStore:
    return DesktopPendingActionStore(tmp_path / "pending_actions.db")


@pytest.fixture
def fixed_speed(monkeypatch):
    """Fija MouseAgent.get_speed() a 10 para todo el test — sin esto se lee
    la velocidad real de Windows, no reproducible en CI."""
    monkeypatch.setattr(MouseAgent, "get_speed", lambda self: 10)


def test_propose_change_creates_pending_without_store(fixed_speed):
    agent = MouseAgent()

    result = agent.propose_change("ctx-1", "up")

    assert result["current"] == 10
    assert result["target"] == 13
    assert agent.has_pending("ctx-1") is True


def test_propose_change_persists_when_store_present(fixed_speed, tmp_path):
    store = _store(tmp_path)
    agent = MouseAgent(store=store)

    agent.propose_change("ctx-1", "max")

    rows = store.list_for_agent("mouse")
    assert len(rows) == 1
    assert rows[0].payload == {"current_value": 10, "target_value": 20, "direction": "max"}


def test_confirm_applies_change_and_forgets_in_store(fixed_speed, monkeypatch, tmp_path):
    store = _store(tmp_path)
    agent = MouseAgent(store=store)
    agent.propose_change("ctx-1", "max")
    monkeypatch.setattr(MouseAgent, "_set_speed", lambda self, value: value)

    result = agent.confirm("ctx-1")

    assert result == {"previous": 10, "applied": 20}
    assert agent.has_pending("ctx-1") is False
    assert store.list_for_agent("mouse") == []


def test_cancel_clears_pending_and_store(fixed_speed, tmp_path):
    store = _store(tmp_path)
    agent = MouseAgent(store=store)
    agent.propose_change("ctx-1", "min")

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert store.list_for_agent("mouse") == []


def test_load_pending_from_store_rehydrates_after_restart(fixed_speed, tmp_path):
    store = _store(tmp_path)
    first_agent = MouseAgent(store=store)
    first_agent.propose_change("ctx-1", "down")

    second_agent = MouseAgent(store=store)
    second_agent.load_pending_from_store()

    assert second_agent.has_pending("ctx-1") is True


def test_load_pending_from_store_without_store_is_a_noop():
    agent = MouseAgent()

    agent.load_pending_from_store()

    assert agent.has_pending("ctx-1") is False


def test_load_pending_from_store_falls_back_to_defaults_for_missing_fields(tmp_path):
    store = _store(tmp_path)
    store.save(agent_id="mouse", context_id="ctx-1", kind="mouse_speed", payload={})

    agent = MouseAgent(store=store)
    agent.load_pending_from_store()

    assert agent.has_pending("ctx-1") is True
