"""tests/unit/test_code_agent.py

CodeAgent (Fase 1 del modo codigo de PEPO): bucle con herramientas de lectura sobre
una carpeta de trabajo AUTORIZADA, con router LLM guionizado y ficheros reales.
"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from desktop.code_agent.agent import CodeAgent
from desktop.storage.code_settings import CodeSettingsStore


def _call(call_id: str, name: str, **args) -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}


def _resp(*calls, content=None):
    return SimpleNamespace(error=None, content=content, tool_calls=list(calls) or None)


class _ScriptedRouter:
    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.seen: list[list[dict]] = []

    async def call(self, messages, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        return self._responses.pop(0)


@pytest.fixture
def settings(tmp_path) -> CodeSettingsStore:
    return CodeSettingsStore(tmp_path / "code_settings.json")


@pytest.fixture
def project(tmp_path, settings):
    root = tmp_path / "proyecto"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def saluda():\n    return 'hola'\n", encoding="utf-8")
    (root / ".env").write_text("API_KEY=abcdef1234567890\n", encoding="utf-8")
    settings.add_workspace(str(root))
    return root


def _agent(router, settings) -> CodeAgent:
    return CodeAgent(None, llm_router=router, settings=settings)


def _tool_result(messages, call_id):
    return dict((m["tool_call_id"], m["content"]) for m in messages if m.get("role") == "tool")[call_id]


@pytest.mark.asyncio
async def test_explores_with_batched_reads_and_answers_with_the_finish_summary(project, settings):
    router = _ScriptedRouter(
        _resp(_call("c1", "grep", pattern="def saluda"), _call("c2", "read_file", path="src/app.py")),
        _resp(_call("c3", "finish", summary="`saluda` esta en src/app.py:1")),
    )

    result = await _agent(router, settings).propose("ctx", "¿donde esta saluda?", workspace=str(project))

    assert result == {"kind": "finish", "task": "¿donde esta saluda?", "summary": "`saluda` esta en src/app.py:1"}
    second_call = router.seen[1]
    assert "src/app.py:1: def saluda():" in _tool_result(second_call, "c1")
    assert "return 'hola'" in _tool_result(second_call, "c2")


@pytest.mark.asyncio
async def test_system_prompt_names_the_workspace_and_says_it_is_read_only(project, settings):
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))

    await _agent(router, settings).propose("ctx", "hola", workspace=str(project))

    system = router.seen[0][0]
    assert system["role"] == "system"
    assert str(project.resolve()) in system["content"]
    assert "SOLO PUEDES LEER" in system["content"]


@pytest.mark.asyncio
async def test_project_rules_file_is_injected_and_redacted(project, settings):
    (project / "PEPO.md").write_text("Usa tipado estricto.\nclave: api_key = 'zzzzzzzzzzzz9999'\n", encoding="utf-8")
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))

    await _agent(router, settings).propose("ctx", "hola", workspace=str(project))

    system = router.seen[0][0]["content"]
    assert "Usa tipado estricto." in system
    assert "zzzzzzzzzzzz9999" not in system


@pytest.mark.asyncio
async def test_the_model_cannot_read_sensitive_files_or_escape_the_workspace(project, settings, tmp_path):
    (tmp_path / "fuera.txt").write_text("TOP SECRET", encoding="utf-8")
    router = _ScriptedRouter(
        _resp(_call("c1", "read_file", path=".env"), _call("c2", "read_file", path="../fuera.txt")),
        _resp(_call("c3", "finish", summary="no pude")),
    )

    await _agent(router, settings).propose("ctx", "lee el .env", workspace=str(project))

    seen = router.seen[1]
    for call_id in ("c1", "c2"):
        assert _tool_result(seen, call_id).startswith("No permitido")
    assert "abcdef1234567890" not in json.dumps(seen) and "TOP SECRET" not in json.dumps(seen)


# ── Autorizacion de la carpeta ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorised_workspace_is_refused_without_calling_the_llm(tmp_path, settings):
    other = tmp_path / "otro"
    other.mkdir()
    router = _ScriptedRouter()

    result = await _agent(router, settings).propose("ctx", "hola", workspace=str(other))

    assert result["kind"] == "finish" and "no esta autorizada" in result["summary"]
    assert router.seen == []


@pytest.mark.asyncio
async def test_missing_or_invalid_workspace_is_explained(settings, tmp_path):
    agent = _agent(_ScriptedRouter(), settings)

    assert "Elige una carpeta" in (await agent.propose("c1", "x", workspace=None))["summary"]
    assert "no existe" in (await agent.propose("c2", "x", workspace=str(tmp_path / "nada")))["summary"]


@pytest.mark.asyncio
async def test_disabled_code_mode_refuses(project, settings):
    settings.set_enabled(False)
    router = _ScriptedRouter()

    result = await _agent(router, settings).propose("ctx", "hola", workspace=str(project))

    assert "desactivado" in result["summary"]
    assert router.seen == []


@pytest.mark.asyncio
async def test_agent_without_settings_never_opens_a_workspace(project):
    result = await CodeAgent(None, llm_router=_ScriptedRouter()).propose("ctx", "hola", workspace=str(project))

    assert "no esta autorizada" in result["summary"]


# ── Preguntas, reanudacion y persistencia ────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_user_keeps_the_workspace_and_resumes_in_the_same_folder(project, settings):
    router = _ScriptedRouter(
        _resp(_call("c1", "ask_user", question="¿que modulo?")),
        _resp(_call("c2", "read_file", path="src/app.py")),
        _resp(_call("c3", "finish", summary="listo")),
    )
    agent = _agent(router, settings)

    asked = await agent.propose("ctx", "explica", workspace=str(project))
    assert asked["kind"] == "ask_user"
    assert agent._pending["ctx"].payload["workspace"] == str(project.resolve())

    result = await agent.confirm("ctx", "src/app.py")

    assert result["is_done"] is True and result["content"] == "listo"
    assert "return 'hola'" in _tool_result(router.seen[2], "c2")  # leyo del workspace correcto tras reanudar


@pytest.mark.asyncio
async def test_resume_after_the_folder_was_deauthorised_discards_the_task(project, settings):
    router = _ScriptedRouter(_resp(_call("c1", "ask_user", question="¿que?")))
    agent = _agent(router, settings)
    await agent.propose("ctx", "explica", workspace=str(project))
    settings.remove_workspace(str(project))

    result = await agent.confirm("ctx", "lo que sea")

    assert result["is_done"] is True and "no esta autorizada" in result["content"]
    assert not agent.has_pending("ctx")
    assert len(router.seen) == 1  # no se volvio a llamar al LLM


@pytest.mark.asyncio
async def test_confirm_and_reject_without_pending_return_none(settings):
    agent = _agent(_ScriptedRouter(), settings)

    assert await agent.confirm("nadie") is None
    assert await agent.reject("nadie") is None


@pytest.mark.asyncio
async def test_two_conversations_in_different_workspaces_do_not_mix(tmp_path, settings):
    roots = []
    for name in ("alfa", "beta"):
        root = tmp_path / name
        root.mkdir()
        (root / "dato.txt").write_text(f"contenido de {name}\n", encoding="utf-8")
        settings.add_workspace(str(root))
        roots.append(root)

    async def run(root, context_id):
        router = _ScriptedRouter(
            _resp(_call("c1", "read_file", path="dato.txt")),
            _resp(_call("c2", "finish", summary="ok")),
        )
        agent = _agent(router, settings)
        await agent.propose(context_id, "lee", workspace=str(root))
        return _tool_result(router.seen[1], "c1")

    alfa, beta = await asyncio.gather(run(roots[0], "a"), run(roots[1], "b"))

    assert "contenido de alfa" in alfa and "beta" not in alfa
    assert "contenido de beta" in beta and "alfa" not in beta


@pytest.mark.asyncio
async def test_phase_one_has_nothing_to_execute(settings):
    from desktop.local_agents.confirmable_loop import PendingAction

    result = await _agent(_ScriptedRouter(), settings).execute(PendingAction(task="x", kind="edit"))

    assert result["error"]


# ── Presupuesto de contexto ──────────────────────────────────────────────────

def test_old_tool_outputs_are_elided_when_the_context_exceeds_the_budget(settings):
    agent = _agent(_ScriptedRouter(), settings)
    messages = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "tarea"}]
    for i in range(20):
        messages.append({"role": "assistant", "content": None, "tool_calls": [_call(f"c{i}", "read_file", path="x")]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 10_000})
    messages.append({"role": "tool", "tool_call_id": "pend", "content": "__pendiente_de_respuesta_del_usuario__"})

    agent._prepare_messages(messages)

    tool_contents = [m["content"] for m in messages if m["role"] == "tool"]
    assert tool_contents[0].startswith("[resultado antiguo omitido")       # lo viejo se omite
    assert tool_contents[-2] == "x" * 10_000                                 # lo reciente se conserva
    assert tool_contents[-1] == "__pendiente_de_respuesta_del_usuario__"     # el marcador no se toca
    assert messages[0]["content"] == "sistema" and messages[1]["content"] == "tarea"
    assert sum(len(str(m.get("content") or "")) for m in messages) <= 100_000 + 10_000


def test_small_contexts_are_left_alone(settings):
    agent = _agent(_ScriptedRouter(), settings)
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "x" * 5_000}]

    agent._prepare_messages(messages)

    assert messages[0]["content"] == "x" * 5_000


# ── Ajustes (carpetas autorizadas) ───────────────────────────────────────────

def test_settings_default_is_enabled_with_no_workspaces(tmp_path):
    store = CodeSettingsStore(tmp_path / "s.json")

    assert store.load() == {"enabled": True, "workspaces": []}


def test_settings_add_dedupes_and_remove_works(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    store = CodeSettingsStore(tmp_path / "s.json")

    store.add_workspace(str(folder))
    store.add_workspace(str(folder))

    assert store.workspaces() == [str(folder.resolve())]
    store.remove_workspace(str(folder))
    assert store.workspaces() == []


def test_settings_refuse_broad_or_missing_folders(tmp_path):
    from desktop.code_agent.workspace import WorkspaceError
    from pathlib import Path

    store = CodeSettingsStore(tmp_path / "s.json")

    for bad in (str(Path.home()), str(Path(Path.home().anchor)), str(tmp_path / "no_existe"), "relativa"):
        with pytest.raises(WorkspaceError):
            store.add_workspace(bad)
    assert store.workspaces() == []


def test_settings_is_allowed_accepts_subfolders_but_not_prefix_siblings(tmp_path):
    folder = tmp_path / "proyecto"
    (folder / "src").mkdir(parents=True)
    sibling = tmp_path / "proyecto-otro"
    sibling.mkdir()
    store = CodeSettingsStore(tmp_path / "s.json")
    store.add_workspace(str(folder))

    assert store.is_allowed(folder) and store.is_allowed(folder / "src")
    assert not store.is_allowed(sibling)
    assert not store.is_allowed(tmp_path)
    assert not store.is_allowed(folder / ".." / "proyecto-otro")


def test_settings_survive_a_corrupted_file(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{no es json", encoding="utf-8")

    assert CodeSettingsStore(path).load() == {"enabled": True, "workspaces": []}
