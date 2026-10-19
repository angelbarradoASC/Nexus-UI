"""tests/unit/test_confirmable_loop_code_mode.py

Fase 0 del "modo codigo" de PEPO (docs/PLAN_PEPO_MODO_CODIGO.md): extensiones
de ConfirmableAgent que un agente tipo Cursor necesita y que estan APAGADAS por
defecto para no cambiar a RemoteOps/SelfConfig/MCP:

- batch_readonly_calls: procesa todas las tool calls del turno (antes solo la 1a).
- resume_after_execute: el resultado de execute() vuelve al LLM y el bucle sigue
  (editar -> probar -> leer el fallo -> corregir); reject() informa al modelo.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.confirmable_loop import ConfirmableAgent, ProposalOutcome


def _call(call_id: str, name: str, **args) -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}


def _resp(*calls, content=None, error=None):
    return SimpleNamespace(error=error, content=content, tool_calls=list(calls) or None)


class _ScriptedRouter:
    """Devuelve respuestas guionizadas y guarda una COPIA de los mensajes de
    cada llamada (el bucle muta la lista, un snapshot es lo que vio el LLM)."""

    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.seen: list[list[dict]] = []
        self.kwargs: list[dict] = []

    async def call(self, messages, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        self.kwargs.append(kwargs)
        return self._responses.pop(0)


class _Agent(ConfirmableAgent):
    tools = []
    prompt_key = "agent.general"
    agent_id = "test-agent"

    def __init__(self, router) -> None:
        super().__init__(None, llm_router=router)
        self.reads: list[str] = []
        self.executed: list[dict] = []

    async def dispatch_tool(self, name, args):
        if name == "read":
            self.reads.append(args["path"])
            return f"contenido de {args['path']}"
        if name == "boom":
            raise RuntimeError("disco roto")
        if name == "edit":
            return ProposalOutcome(kind="edit", payload=dict(args))
        return None

    async def execute(self, pending):
        self.executed.append(pending.payload)
        return {"task": pending.task, "is_done": False, "content": f"Editado {pending.payload['path']}", "error": None}


class _CodeAgent(_Agent):
    batch_readonly_calls = True
    resume_after_execute = True
    max_loop_steps = 10
    preferred_level = 3
    max_tokens = 3000
    loop_timeout = 60.0


def _tool_messages(messages):
    return [(m["tool_call_id"], m["content"]) for m in messages if m.get("role") == "tool"]


# ── Compatibilidad: por defecto nada cambia ──────────────────────────────────

@pytest.mark.asyncio
async def test_default_agent_still_processes_only_the_first_tool_call():
    router = _ScriptedRouter(
        _resp(_call("c1", "read", path="a.py"), _call("c2", "read", path="b.py")),
        _resp(_call("c3", "finish", summary="listo")),
    )
    agent = _Agent(router)

    result = await agent.propose("ctx", "lee cosas")

    assert agent.reads == ["a.py"]
    assert result == {"kind": "finish", "task": "lee cosas", "summary": "listo"}
    ignored = dict(_tool_messages(router.seen[1]))
    assert "Ignorada" in ignored["c2"]


@pytest.mark.asyncio
async def test_default_agent_confirm_still_ends_after_execute():
    router = _ScriptedRouter(_resp(_call("c1", "edit", path="a.py")))
    agent = _Agent(router)
    await agent.propose("ctx", "edita")

    result = await agent.confirm("ctx")

    assert result["content"] == "Editado a.py"
    assert len(router.seen) == 1  # el LLM no vuelve a ser consultado
    assert not agent.has_pending("ctx")


@pytest.mark.asyncio
async def test_default_llm_parameters_are_the_historic_ones():
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))
    await _Agent(router).propose("ctx", "x")

    assert (router.kwargs[0]["preferred_level"], router.kwargs[0]["max_tokens"], router.kwargs[0]["timeout"]) == (2, 1400, 30.0)


@pytest.mark.asyncio
async def test_llm_parameters_are_configurable_per_agent():
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))
    await _CodeAgent(router).propose("ctx", "x")

    assert (router.kwargs[0]["preferred_level"], router.kwargs[0]["max_tokens"], router.kwargs[0]["timeout"]) == (3, 3000, 60.0)


# ── Lecturas en lote ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_runs_every_read_of_the_turn_and_continues():
    router = _ScriptedRouter(
        _resp(_call("c1", "read", path="a.py"), _call("c2", "read", path="b.py")),
        _resp(_call("c3", "finish", summary="leidos")),
    )
    agent = _CodeAgent(router)

    result = await agent.propose("ctx", "lee dos")

    assert agent.reads == ["a.py", "b.py"]
    assert result["summary"] == "leidos"
    assert _tool_messages(router.seen[1]) == [("c1", "contenido de a.py"), ("c2", "contenido de b.py")]


@pytest.mark.asyncio
async def test_batch_stops_at_the_first_proposal_and_ignores_the_calls_after_it():
    router = _ScriptedRouter(
        _resp(_call("c1", "read", path="a.py"), _call("c2", "edit", path="a.py"), _call("c3", "read", path="b.py")),
    )
    agent = _CodeAgent(router)

    result = await agent.propose("ctx", "edita")

    assert result["kind"] == "edit"
    assert agent.reads == ["a.py"]  # la lectura posterior a la propuesta NO se ejecuta
    assert agent.has_pending("ctx")
    msgs = _tool_messages(agent._pending["ctx"].messages)
    # un mensaje tool por cada tool call, en el MISMO orden que las calls
    assert [call_id for call_id, _ in msgs] == ["c1", "c2", "c3"]
    assert "Ignorada" in msgs[2][1]


@pytest.mark.asyncio
async def test_batch_returns_invalid_json_arguments_to_the_model_instead_of_dying():
    bad = {"id": "c1", "function": {"name": "read", "arguments": "{no es json"}}
    router = _ScriptedRouter(_resp(bad), _resp(_call("c2", "finish", summary="reintentado")))
    agent = _CodeAgent(router)

    result = await agent.propose("ctx", "x")

    assert result["summary"] == "reintentado"
    assert "JSON invalidos" in dict(_tool_messages(router.seen[1]))["c1"]
    assert agent.reads == []


@pytest.mark.asyncio
async def test_batch_returns_a_tool_exception_to_the_model_instead_of_dying():
    router = _ScriptedRouter(_resp(_call("c1", "boom")), _resp(_call("c2", "finish", summary="visto")))
    agent = _CodeAgent(router)

    result = await agent.propose("ctx", "x")

    assert result["summary"] == "visto"
    assert "disco roto" in dict(_tool_messages(router.seen[1]))["c1"]


@pytest.mark.asyncio
async def test_batch_ask_user_waits_and_the_answer_replaces_the_marker_in_place():
    router = _ScriptedRouter(
        _resp(_call("c1", "ask_user", question="¿que fichero?"), _call("c2", "read", path="a.py")),
        _resp(_call("c3", "finish", summary="ok")),
    )
    agent = _CodeAgent(router)

    asked = await agent.propose("ctx", "x")
    assert asked["kind"] == "ask_user"

    result = await agent.confirm("ctx", "main.py")

    assert result["is_done"] is True
    msgs = _tool_messages(router.seen[1])
    assert msgs[0] == ("c1", "main.py")  # la respuesta ocupa el lugar de la call, no va al final
    assert "Ignorada" in msgs[1][1]


# ── Reanudar tras ejecutar ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_feeds_the_execution_result_back_and_the_loop_continues():
    router = _ScriptedRouter(
        _resp(_call("c1", "edit", path="a.py")),
        _resp(_call("c2", "finish", summary="Corregido y verificado")),
    )
    agent = _CodeAgent(router)
    proposal = await agent.propose("ctx", "edita a.py")
    assert proposal["kind"] == "edit"

    result = await agent.confirm("ctx")

    assert agent.executed == [{"path": "a.py"}]
    assert result["is_done"] is True
    assert result["content"] == "Corregido y verificado"
    assert result["executed"]["content"] == "Editado a.py"
    # el LLM vio el resultado real de la ejecucion como resultado de su tool call
    assert dict(_tool_messages(router.seen[1]))["c1"] == "Editado a.py"
    assert not agent.has_pending("ctx")


@pytest.mark.asyncio
async def test_resume_an_execution_error_goes_back_to_the_model_so_it_can_fix_it():
    router = _ScriptedRouter(
        _resp(_call("c1", "edit", path="a.py")),
        _resp(_call("c2", "finish", summary="lo he reintentado")),
    )
    agent = _CodeAgent(router)

    async def failing_execute(pending):
        return {"task": pending.task, "is_done": False, "content": None, "error": "old_string no encontrado"}

    agent.execute = failing_execute
    await agent.propose("ctx", "edita")

    result = await agent.confirm("ctx")

    assert "ERROR: old_string no encontrado" in dict(_tool_messages(router.seen[1]))["c1"]
    assert result["is_done"] is True


@pytest.mark.asyncio
async def test_resume_can_chain_into_a_second_proposal():
    router = _ScriptedRouter(
        _resp(_call("c1", "edit", path="a.py")),
        _resp(_call("c2", "edit", path="b.py")),
    )
    agent = _CodeAgent(router)
    await agent.propose("ctx", "edita dos")

    second = await agent.confirm("ctx")

    assert second["is_done"] is False
    assert second["next_kind"] == "edit"
    assert second["next_payload"] == {"path": "b.py"}
    assert agent.has_pending("ctx")  # la segunda propuesta espera su aprobacion


@pytest.mark.asyncio
async def test_resume_stops_after_max_loop_steps():
    router = _ScriptedRouter(*[_resp(_call(f"r{i}", "read", path="a.py")) for i in range(3)])
    agent = _CodeAgent(router)
    agent.max_loop_steps = 3

    result = await agent.propose("ctx", "x")

    assert result["kind"] == "finish"
    assert "pasos disponibles" in result["summary"]


# ── Rechazo ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reject_tells_the_model_and_lets_it_propose_something_else():
    router = _ScriptedRouter(
        _resp(_call("c1", "edit", path="a.py")),
        _resp(_call("c2", "finish", summary="Entendido, no toco a.py")),
    )
    agent = _CodeAgent(router)
    await agent.propose("ctx", "edita")

    result = await agent.reject("ctx", "mejor en b.py")

    assert agent.executed == []  # nada se ejecuto
    assert result["content"] == "Entendido, no toco a.py"
    sent = dict(_tool_messages(router.seen[1]))["c1"]
    assert "RECHAZADO" in sent and "mejor en b.py" in sent


@pytest.mark.asyncio
async def test_reject_without_resume_mode_is_a_plain_cancel():
    router = _ScriptedRouter(_resp(_call("c1", "edit", path="a.py")))
    agent = _Agent(router)
    await agent.propose("ctx", "edita")

    result = await agent.reject("ctx")

    assert result["content"] == "Cancelado."
    assert not agent.has_pending("ctx")
    assert len(router.seen) == 1


@pytest.mark.asyncio
async def test_reject_with_nothing_pending_returns_none():
    assert await _CodeAgent(_ScriptedRouter()).reject("nadie") is None
