"""tests/unit/test_system_task_agent_self_healing.py

Regresion de espiritu, no de bug puntual: antes, cuando un script YA
CONFIRMADO fallaba (timeout o codigo de error), ese fallo era la respuesta
final del turno — el usuario tenia que volver a pedir la tarea desde cero,
y cada fallo nuevo (un timeout corto, un permiso que faltaba...) exigia que
alguien ajustara una constante en el codigo. Ahora el fallo se devuelve al
propio bucle de PEPO como un resultado de herramienta mas, igual que ya
hacia con ask_user, para que el LLM decida como seguir — acotar el
alcance, preguntar, o explicar el motivo — sin intervencion humana en el
codigo por cada fallo nuevo. Acotado por _MAX_AUTO_RETRIES para no
encadenar llamadas al LLM sin limite ante un fallo persistente.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from desktop.local_agents.system_task_agent import (
    _MAX_AUTO_RETRIES,
    PendingSystemTask,
    SystemTaskAgent,
)


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
        self.call_count = 0

    async def call(self, **kwargs):
        self.call_count += 1
        return self._responses.pop(0)


async def _no_validation_problems(script: str) -> list[str]:
    return []


def _always_times_out(script, *, timeout=60.0, env=None):
    raise subprocess.TimeoutExpired(cmd=script, timeout=timeout)


@pytest.mark.asyncio
async def test_failed_script_is_fed_back_to_the_llm_instead_of_ending_the_task(monkeypatch):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "run_script", script="Get-ChildItem C:\\ -Recurse", description="rastreo completo",
        )]),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "run_script", script="Get-ChildItem C:\\Users\\angel\\Documents -Recurse",
            description="rastreo acotado a Documents",
        )]),
    ])
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=llm, store=None)
    agent._validate_script = _no_validation_problems
    monkeypatch.setattr("desktop.local_agents.system_task_agent._run_powershell", _always_times_out)

    await agent.propose("ctx-1", "busca PDFs con 'auto' en todo el disco")
    result = await agent.confirm("ctx-1")

    assert llm.call_count == 2
    assert result["next_script"] == "Get-ChildItem C:\\Users\\angel\\Documents -Recurse"
    assert result["next_description"] == "rastreo acotado a Documents"
    # el reintento vuelve a exigir confirmacion humana, no se ejecuta solo
    assert agent.has_pending("ctx-1") is True


@pytest.mark.asyncio
async def test_llm_can_ask_the_user_instead_of_retrying_blindly(monkeypatch):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "run_script", script="Get-ChildItem C:\\ -Recurse", description="rastreo completo",
        )]),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "ask_user", question="¿En que carpeta busco en vez de todo el disco?",
        )]),
    ])
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=llm, store=None)
    agent._validate_script = _no_validation_problems
    monkeypatch.setattr("desktop.local_agents.system_task_agent._run_powershell", _always_times_out)

    await agent.propose("ctx-1", "busca PDFs con 'auto' en todo el disco")
    result = await agent.confirm("ctx-1")

    assert result["next_question"] == "¿En que carpeta busco en vez de todo el disco?"


@pytest.mark.asyncio
async def test_retries_are_capped_and_eventually_surface_the_real_error(monkeypatch):
    responses = [
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c0", "run_script", script="Get-ChildItem C:\\ -Recurse", description="intento inicial",
        )]),
    ]
    for i in range(_MAX_AUTO_RETRIES):
        responses.append(_FakeLLMResponse(tool_calls=[_tool_call(
            f"c{i + 1}", "run_script", script=f"Get-ChildItem C:\\intento{i} -Recurse",
            description=f"intento {i + 1}",
        )]))
    llm = _FakeLLMRouter(responses)
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=llm, store=None)
    agent._validate_script = _no_validation_problems
    monkeypatch.setattr("desktop.local_agents.system_task_agent._run_powershell", _always_times_out)

    await agent.propose("ctx-1", "busca PDFs con 'auto' en todo el disco")

    result = None
    for _ in range(_MAX_AUTO_RETRIES + 1):
        result = await agent.confirm("ctx-1")

    # se agotaron los reintentos automaticos: el fallo real llega al usuario
    # en vez de encadenar llamadas al LLM sin limite
    assert result.get("next_script") is None
    assert result["error"] is not None
    assert agent.has_pending("ctx-1") is False


@pytest.mark.asyncio
async def test_skill_match_failure_also_goes_through_the_llm_loop(monkeypatch):
    """skill_match se ejecuta directo (sin pasar por el bucle LLM) — el fallo
    tiene que poder reentrar el bucle igual que run_script, aunque no haya
    historial de mensajes previo."""
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "run_script", script="Get-ChildItem C:\\Documents -Recurse", description="acotado",
        )]),
    ])
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=llm, store=None)
    agent._validate_script = _no_validation_problems
    monkeypatch.setattr("desktop.local_agents.system_task_agent._run_powershell", _always_times_out)

    agent._set_pending("ctx-1", PendingSystemTask(
        task="busca PDFs", kind="skill_match", skill_id="skill-1",
        script="Get-ChildItem C:\\ -Recurse", description="skill guardada",
    ))

    result = await agent.confirm("ctx-1")

    assert llm.call_count == 1
    assert result["next_script"] == "Get-ChildItem C:\\Documents -Recurse"
