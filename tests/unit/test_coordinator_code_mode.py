"""tests/unit/test_coordinator_code_mode.py

Cableado del modo codigo de PEPO (Fase 1): mode="code" va DIRECTO al CodeAgent
(sin clasificador de intencion ni otras confirmaciones pendientes), la carpeta de
trabajo llega entera, y las preguntas del agente se reanudan en el siguiente turno.
"""

from __future__ import annotations

import pytest

from nexus.api.schemas.chat import ChatRequest
from nexus.application.services.assistant_runtime_core import AssistantExecutionRequest, AssistantRuntimeCore
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


class _FakeCodeAgent:
    def __init__(self, *outcomes, confirm_result=None) -> None:
        self._outcomes = list(outcomes)
        self._confirm_result = confirm_result
        self.pending = False
        self.proposed: list[dict] = []
        self.confirmed: list[tuple] = []

    def has_pending(self, context_id: str) -> bool:
        return self.pending

    async def propose(self, context_id, task, *, history=None, workspace=None):
        self.proposed.append({"context_id": context_id, "task": task, "workspace": workspace, "history": history})
        outcome = self._outcomes.pop(0)
        self.pending = outcome["kind"] in {"ask_user", "ask_user_secret"}
        return outcome

    async def confirm(self, context_id, user_reply=None):
        self.confirmed.append((context_id, user_reply))
        self.pending = False
        return self._confirm_result

    async def list_pending(self):
        return [{"context_id": "ctx", "agent_id": "code", "kind": "ask_user", "summary": "x"}] if self.pending else []


class _HijackingMouse:
    """Si el modo codigo no se aislara, esto secuestraria el mensaje."""

    def __init__(self) -> None:
        self.touched = False

    def has_pending(self, context_id: str) -> bool:
        self.touched = True
        return True

    def cancel(self, context_id: str) -> None:
        self.touched = True


def _coordinator(code_agent=None, **extra) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None, grafana=None, prometheus=None,
        incident_repository=MemoryIncidentRepository(), audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(), code_agent=code_agent, **extra,
    )


def _code_request(message: str, workspace: str | None = r"C:\DEV\proyecto") -> ChatRequest:
    return ChatRequest(message=message, mode="code", context_id="ctx", workspace=workspace)


@pytest.mark.asyncio
async def test_code_mode_goes_straight_to_the_code_agent_with_workspace_and_history():
    agent = _FakeCodeAgent({"kind": "finish", "summary": "La respuesta es X (src/a.py:3)."})
    coordinator = _coordinator(agent)
    history = [{"role": "user", "content": "hola"}]

    response = await coordinator.handle_chat(_code_request("explica el modulo a"), history=history)

    assert response.response == "La respuesta es X (src/a.py:3)."
    assert response.agent == "code-agent" and response.status == "accepted"
    assert agent.proposed == [
        {"context_id": "ctx", "task": "explica el modulo a", "workspace": r"C:\DEV\proyecto", "history": history}
    ]


@pytest.mark.asyncio
async def test_code_mode_is_not_hijacked_by_other_pending_confirmations():
    mouse = _HijackingMouse()
    agent = _FakeCodeAgent({"kind": "finish", "summary": "ok"})
    coordinator = _coordinator(agent, mouse_agent=mouse)

    response = await coordinator.handle_chat(_code_request("mira el repo"))

    assert response.response == "ok"
    assert mouse.touched is False


@pytest.mark.asyncio
async def test_other_modes_never_reach_the_code_agent():
    agent = _FakeCodeAgent()
    coordinator = _coordinator(agent)

    await coordinator.handle_chat(ChatRequest(message="hola", mode="general", context_id="ctx"))

    assert agent.proposed == []


@pytest.mark.asyncio
async def test_agent_question_is_shown_and_the_next_message_resumes_it():
    agent = _FakeCodeAgent(
        {"kind": "ask_user", "question": "¿Que modulo?"},
        confirm_result={"is_done": True, "content": "Es el modulo b (b.py:1)."},
    )
    coordinator = _coordinator(agent)

    first = await coordinator.handle_chat(_code_request("explica"))
    second = await coordinator.handle_chat(_code_request("el modulo b"))

    assert first.response == "¿Que modulo?"
    assert agent.confirmed == [("ctx", "el modulo b")]
    assert second.response == "Es el modulo b (b.py:1)."
    assert len(agent.proposed) == 1  # la segunda vez NO empieza una tarea nueva


@pytest.mark.asyncio
async def test_a_follow_up_question_after_resume_is_shown():
    agent = _FakeCodeAgent(
        {"kind": "ask_user", "question": "¿Que modulo?"},
        confirm_result={"is_done": False, "content": None, "next_kind": "ask_user", "next_question": "¿Y que version?"},
    )
    coordinator = _coordinator(agent)
    await coordinator.handle_chat(_code_request("explica"))

    second = await coordinator.handle_chat(_code_request("el b"))

    assert second.response == "¿Y que version?"


@pytest.mark.asyncio
async def test_secret_questions_ask_the_ui_to_redact_the_reply():
    agent = _FakeCodeAgent({"kind": "ask_user_secret", "question": "¿Contraseña?"})

    response = await _coordinator(agent).handle_chat(_code_request("conecta"))

    assert response.redact_next_reply is True


@pytest.mark.asyncio
async def test_without_a_code_agent_the_user_gets_a_clear_message():
    response = await _coordinator(None).handle_chat(_code_request("hola"))

    assert "no esta disponible" in response.response
    assert response.status == "degraded"


@pytest.mark.asyncio
async def test_unsupported_proposal_kinds_do_not_crash_the_chat():
    agent = _FakeCodeAgent({"kind": "edit", "payload": {"path": "a.py"}})

    response = await _coordinator(agent).handle_chat(_code_request("edita"))

    assert "aun no esta soportada" in response.response


@pytest.mark.asyncio
async def test_pending_code_actions_are_listed_and_confirmable_from_the_agents_panel():
    agent = _FakeCodeAgent({"kind": "ask_user", "question": "¿Que?"}, confirm_result={"is_done": True, "content": "ok"})
    coordinator = _coordinator(agent)
    await coordinator.handle_chat(_code_request("explica"))

    listed = await coordinator.list_pending_actions()
    confirmed = await coordinator.confirm_pending_action("ctx", "respuesta")

    assert [item["agent_id"] for item in listed] == ["code"]
    assert confirmed["status"] == "ok" and agent.confirmed == [("ctx", "respuesta")]


# ── Pipeline completo (runtime) ──────────────────────────────────────────────

class _ExplodingRouter:
    """Si el runtime llamara al clasificador de intencion en modo codigo, esto falla."""

    async def call(self, *args, **kwargs):
        raise AssertionError("el modo codigo no debe llamar al clasificador de intencion")


@pytest.mark.asyncio
async def test_runtime_skips_the_intent_classifier_and_forwards_the_workspace():
    agent = _FakeCodeAgent({"kind": "finish", "summary": "hecho"})
    runtime = AssistantRuntimeCore(_coordinator(agent), llm_router=_ExplodingRouter())

    result = await runtime.execute(
        AssistantExecutionRequest(
            message="explica", mode="code", context_id="ctx", workspace=r"C:\DEV\proyecto", source_surface="desktop"
        )
    )

    assert result.response == "hecho"
    assert result.resolution["skill_id"] == "code.agent"
    assert agent.proposed[0]["workspace"] == r"C:\DEV\proyecto"
