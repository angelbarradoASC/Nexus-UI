"""tests/unit/test_system_task_agent_persistence.py

Tests de persistencia para SystemTaskAgent — el estado pendiente (via
_set_pending/_clear_pending) debe sobrevivir un reinicio del proceso a
traves de DesktopPendingActionStore. No es una suite de regresion completa
del agente (eso queda para otra sesion) — cubre especificamente el cableado
de persistencia añadido.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.system_task_agent import SystemTaskAgent
from desktop.storage.pending_actions import DesktopPendingActionStore


class _FakeLLMResponse:
    def __init__(self, *, tool_calls=None, content=None, error=None):
        self.tool_calls = tool_calls
        self.content = content
        self.error = error


def _tool_call(call_id: str, tool_name: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": tool_name, "arguments": json.dumps(arguments)}}


class _FakeLLMRouter:
    def __init__(self, responses: list[_FakeLLMResponse]):
        self._responses = list(responses)

    async def call(self, **kwargs):
        return self._responses.pop(0)


def _store(tmp_path) -> DesktopPendingActionStore:
    return DesktopPendingActionStore(tmp_path / "pending_actions.db")


async def _no_validation_problems(script: str) -> list[str]:
    return []


# ── Camino sin LLM (windows_use directo) ────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_without_llm_router_persists_windows_use_pending(tmp_path):
    store = _store(tmp_path)
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=None, store=store)

    result = await agent.propose("ctx-1", "abre el panel de control")

    assert result["kind"] == "windows_use"
    assert agent.has_pending("ctx-1") is True
    rows = store.list_for_agent("system_task")
    assert len(rows) == 1
    assert rows[0].kind == "windows_use"


@pytest.mark.asyncio
async def test_cancel_clears_pending_and_store(tmp_path):
    store = _store(tmp_path)
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=None, store=store)
    await agent.propose("ctx-1", "abre el panel de control")

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert store.list_for_agent("system_task") == []


@pytest.mark.asyncio
async def test_load_pending_from_store_rehydrates_windows_use(tmp_path):
    store = _store(tmp_path)
    first_agent = SystemTaskAgent(SimpleNamespace(), llm_router=None, store=store)
    await first_agent.propose("ctx-1", "abre el panel de control")

    second_agent = SystemTaskAgent(SimpleNamespace(), llm_router=None, store=store)
    second_agent.load_pending_from_store()

    assert second_agent.has_pending("ctx-1") is True
    assert second_agent.pending_kind("ctx-1") == "windows_use"


# ── Camino con LLM (run_script) — verifica el payload extra ────────────────

@pytest.mark.asyncio
async def test_run_script_pending_persists_script_fields(tmp_path):
    store = _store(tmp_path)
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "run_script", script="Get-Date", verify_command="Get-Date",
            description="Muestra la fecha",
        )]),
    ])
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=llm, store=store)
    agent._validate_script = _no_validation_problems  # evita invocar PowerShell real

    result = await agent.propose("ctx-1", "dime la fecha")

    assert result["kind"] == "run_script"
    rows = store.list_for_agent("system_task")
    assert len(rows) == 1
    assert rows[0].payload["script"] == "Get-Date"
    assert rows[0].payload["description"] == "Muestra la fecha"


@pytest.mark.asyncio
async def test_load_pending_from_store_rehydrates_run_script_payload(tmp_path):
    store = _store(tmp_path)
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "run_script", script="Get-Date", verify_command="", description="Muestra la fecha",
        )]),
    ])
    first_agent = SystemTaskAgent(SimpleNamespace(), llm_router=llm, store=store)
    first_agent._validate_script = _no_validation_problems
    await first_agent.propose("ctx-1", "dime la fecha")

    second_agent = SystemTaskAgent(SimpleNamespace(), llm_router=None, store=store)
    second_agent.load_pending_from_store()

    assert second_agent.has_pending("ctx-1") is True
    assert second_agent.pending_kind("ctx-1") == "run_script"
    rehydrated = second_agent._pending["ctx-1"]
    assert rehydrated.script == "Get-Date"
    assert rehydrated.description == "Muestra la fecha"
