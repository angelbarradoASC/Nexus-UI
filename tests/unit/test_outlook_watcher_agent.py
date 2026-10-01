"""tests/unit/test_outlook_watcher_agent.py

OutlookWatcherAgent — vigila Outlook en segundo plano y avisa por
iniciativa propia (notificacion + conversacion de PEPO ya escrita), sin
esperar a que el usuario pregunte. Mismo molde que MonitoringAgent, pero
hablando con /api/nexus/outlook/priority y /api/desktop/pepo/
conversations/proactive por HTTP (se mockea httpx.get/post; la
deduplicacion persistente en disco se prueba de verdad, sin mockear).
"""

from __future__ import annotations

import json

import pytest

from desktop.local_agents import outlook_watcher_agent as module
from desktop.local_agents.outlook_watcher_agent import OutlookWatcherAgent


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


def _priority_payload(messages: list[dict]) -> dict:
    return {"status": "success", "messages": messages}


def _message(message_id: str, *, importance: str = "high", sender: str = "Laura", subject: str = "Propuesta", reason: str = "cliente importante") -> dict:
    return {
        "message_id": message_id,
        "sender_name": sender,
        "sender_email": f"{sender.lower()}@example.com",
        "subject": subject,
        "importance": importance,
        "reason": reason,
    }


def _agent(tmp_path, *, get_responses, post_log, notify_log, monkeypatch, importance_threshold: str = "high") -> OutlookWatcherAgent:
    def fake_get(url, headers=None, timeout=None):
        return get_responses.pop(0)

    def fake_post(url, json=None, headers=None, timeout=None):
        post_log.append((url, json))
        return _FakeResponse({"available": True})

    monkeypatch.setattr(module.httpx, "get", fake_get)
    monkeypatch.setattr(module.httpx, "post", fake_post)

    def notify_fn(message, title):
        notify_log.append((message, title))

    return OutlookWatcherAgent(
        local_url="http://127.0.0.1:11430",
        importance_threshold=importance_threshold,
        notify_fn=notify_fn,
        notified_path=tmp_path / "outlook_notified.json",
    )


def test_tick_notifies_for_new_important_message(tmp_path, monkeypatch):
    get_responses = [_FakeResponse(_priority_payload([_message("msg-1")]))]
    post_log: list = []
    notify_log: list = []
    agent = _agent(tmp_path, get_responses=get_responses, post_log=post_log, notify_log=notify_log, monkeypatch=monkeypatch)

    agent._tick()

    assert len(notify_log) == 1
    assert "Laura" in notify_log[0][0]
    assert len(post_log) == 1
    assert post_log[0][0].endswith("/api/desktop/pepo/conversations/proactive")
    assert "Laura" in post_log[0][1]["first_message"]
    assert "Propuesta" in post_log[0][1]["first_message"]


def test_tick_skips_messages_below_importance_threshold(tmp_path, monkeypatch):
    get_responses = [_FakeResponse(_priority_payload([_message("msg-1", importance="medium")]))]
    post_log: list = []
    notify_log: list = []
    agent = _agent(tmp_path, get_responses=get_responses, post_log=post_log, notify_log=notify_log, monkeypatch=monkeypatch)

    agent._tick()

    assert notify_log == []
    assert post_log == []


def test_tick_never_renotifies_the_same_message_id(tmp_path, monkeypatch):
    """Deduplicacion REAL (fichero en disco, no solo en memoria) — un
    correo ya avisado no debe volver a interrumpir al usuario, ni siquiera
    tras 'reiniciar' el agente (segunda instancia sobre el mismo path)."""
    message = _message("msg-1")
    post_log: list = []
    notify_log: list = []
    get_responses = [_FakeResponse(_priority_payload([message]))]
    agent = _agent(tmp_path, get_responses=get_responses, post_log=post_log, notify_log=notify_log, monkeypatch=monkeypatch)
    agent._tick()
    assert len(notify_log) == 1

    # Segunda instancia, mismo fichero de dedup — simula un reinicio real.
    get_responses_2 = [_FakeResponse(_priority_payload([message]))]
    agent2 = _agent(tmp_path, get_responses=get_responses_2, post_log=post_log, notify_log=notify_log, monkeypatch=monkeypatch)
    agent2._tick()

    assert len(notify_log) == 1  # sigue en 1 — no se repitio


def test_tick_handles_not_authenticated_without_crashing(tmp_path, monkeypatch):
    get_responses = [_FakeResponse({"status": "not_authenticated", "messages": []})]
    post_log: list = []
    notify_log: list = []
    agent = _agent(tmp_path, get_responses=get_responses, post_log=post_log, notify_log=notify_log, monkeypatch=monkeypatch)

    agent._tick()  # no debe lanzar

    assert notify_log == []


def test_tick_handles_server_unreachable_without_crashing(tmp_path, monkeypatch):
    def failing_get(url, headers=None, timeout=None):
        raise ConnectionError("servidor local no listo todavia")

    monkeypatch.setattr(module.httpx, "get", failing_get)
    agent = OutlookWatcherAgent(local_url="http://127.0.0.1:11430", notified_path=tmp_path / "outlook_notified.json")

    agent._tick()  # no debe lanzar


def test_notified_ids_persist_to_real_json_file(tmp_path, monkeypatch):
    notified_path = tmp_path / "outlook_notified.json"
    get_responses = [_FakeResponse(_priority_payload([_message("msg-1"), _message("msg-2")]))]
    post_log: list = []
    notify_log: list = []
    agent = OutlookWatcherAgent(
        local_url="http://127.0.0.1:11430",
        notify_fn=lambda m, t: notify_log.append((m, t)),
        notified_path=notified_path,
    )
    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: get_responses.pop(0))
    monkeypatch.setattr(module.httpx, "post", lambda *a, **k: post_log.append(1) or _FakeResponse({}))

    agent._tick()

    assert notified_path.exists()
    saved = json.loads(notified_path.read_text(encoding="utf-8"))
    assert set(saved) == {"msg-1", "msg-2"}
