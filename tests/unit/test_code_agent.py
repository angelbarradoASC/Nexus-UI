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


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    """El pacer real esperaria segundos de verdad; aqui solo se prueba el bucle."""
    monkeypatch.setattr(CodeAgent, "tokens_per_minute", 10**9)
    # La revision de "terminar sin mirar nada" tiene sus propios tests (abajo); aqui se probaria
    # a ciegas la mecanica del bucle con respuestas que terminan directamente.
    monkeypatch.setattr(CodeAgent, "max_finish_reviews", 0)


@pytest.fixture
def settings(tmp_path) -> CodeSettingsStore:
    store = CodeSettingsStore(tmp_path / "code_settings.json")
    store.set_tokens_per_minute(1_000_000)   # que el pacer no espere de verdad en estos tests
    return store


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

def _agent_with_default_quota(tmp_path) -> CodeAgent:
    """Agente con la cuota por defecto (6.500 tokens/min) para probar el recorte de contexto."""
    return CodeAgent(None, llm_router=_ScriptedRouter(), settings=CodeSettingsStore(tmp_path / "default.json"))


def _conversation(results: list[int]) -> list[dict]:
    messages = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "tarea"}]
    for i, size in enumerate(results):
        messages.append({"role": "assistant", "content": None, "tool_calls": [_call(f"c{i}", "read_file", path="x")]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * size})
    return messages


def _chars(messages) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def test_old_tool_outputs_are_elided_oldest_first_until_the_context_fits(tmp_path):
    agent = _agent_with_default_quota(tmp_path)
    messages = _conversation([4_000] * 8)
    messages.append({"role": "tool", "tool_call_id": "pend", "content": "__pendiente_de_respuesta_del_usuario__"})
    budget = agent._context_char_budget()

    agent._prepare_messages(messages)

    contents = [m["content"] for m in messages if m["role"] == "tool"]
    assert contents[0].startswith("[resultado antiguo omitido")                 # lo viejo se omite primero
    assert contents[-2] == "x" * 4_000                                           # lo reciente se conserva
    assert contents[-1] == "__pendiente_de_respuesta_del_usuario__"              # el marcador no se toca
    assert messages[0]["content"] == "sistema" and messages[1]["content"] == "tarea"
    assert _chars(messages) <= budget


def test_the_context_never_exceeds_the_budget_even_with_one_huge_result(tmp_path):
    """Visto en vivo: el contexto crecia sin tope (estimacion de 8,3k a 9,6k tokens), cada
    paso esperaba un minuto entero y la tarea seguia 10 minutos."""
    agent = _agent_with_default_quota(tmp_path)
    messages = _conversation([1_000, 1_000, 60_000])
    budget = agent._context_char_budget()

    agent._prepare_messages(messages)

    last = [m for m in messages if m["role"] == "tool"][-1]["content"]
    assert last.endswith("pide un trozo mas pequeño si lo necesitas]")
    assert _chars(messages) <= budget


def test_small_contexts_are_left_alone(tmp_path):
    agent = _agent_with_default_quota(tmp_path)
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "x" * 5_000}]

    agent._prepare_messages(messages)

    assert messages[0]["content"] == "x" * 5_000


def test_the_context_budget_scales_with_the_configured_quota(tmp_path):
    low = CodeSettingsStore(tmp_path / "a.json")
    high = CodeSettingsStore(tmp_path / "b.json")
    high.set_tokens_per_minute(100_000)

    low_budget = CodeAgent(None, settings=low)._context_char_budget()
    high_budget = CodeAgent(None, settings=high)._context_char_budget()

    assert low_budget < 20_000 < 100_000 < high_budget
    # y una peticion de ese tamaño cabe en la cuota (mensajes + esquemas de herramientas)
    assert (low_budget + 3_100) / 3.3 < low.tokens_per_minute


# ── Ajustes (carpetas autorizadas) ───────────────────────────────────────────

def test_settings_default_is_enabled_with_no_workspaces(tmp_path):
    store = CodeSettingsStore(tmp_path / "s.json")

    assert store.load() == {"enabled": True, "workspaces": [], "tokens_per_minute": 6500, "llm": {"base_url": "", "model": "", "num_ctx": 8192, "think": False}}


def test_tokens_per_minute_is_stored_and_clamped(tmp_path):
    store = CodeSettingsStore(tmp_path / "s.json")

    assert store.set_tokens_per_minute(50_000)["tokens_per_minute"] == 50_000
    assert store.tokens_per_minute == 50_000
    assert store.set_tokens_per_minute(5)["tokens_per_minute"] == 1_000
    assert store.set_tokens_per_minute(10**9)["tokens_per_minute"] == 1_000_000


def test_a_garbage_tokens_per_minute_falls_back_to_the_default(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"tokens_per_minute": "mucho"}', encoding="utf-8")

    assert CodeSettingsStore(path).tokens_per_minute == 6500


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

    assert CodeSettingsStore(path).load() == {"enabled": True, "workspaces": [], "tokens_per_minute": 6500, "llm": {"base_url": "", "model": "", "num_ctx": 8192, "think": False}}


# ── Evidencia obligatoria ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_answer_without_looking_at_any_file_is_pushed_back_once(project, settings, monkeypatch):
    monkeypatch.setattr(CodeAgent, "max_finish_reviews", 1)
    """Medido: qwen2.5-coder:3b contesto en 2 s con una frase generica sin usar ninguna herramienta."""
    router = _ScriptedRouter(
        _resp(_call("c1", "finish", summary="El historial se pasa al clasificador.")),
        _resp(_call("c2", "grep", pattern="def saluda")),
        _resp(_call("c3", "finish", summary="saluda esta en src/app.py:1")),
    )

    result = await _agent(router, settings).propose("ctx", "¿donde esta saluda?", workspace=str(project))

    assert result["summary"] == "saluda esta en src/app.py:1"
    objection = _tool_result(router.seen[1], "c1")
    assert "No has consultado ningun fichero" in objection and "ruta:linea" in objection


@pytest.mark.asyncio
async def test_repeating_the_same_answer_after_the_objection_is_accepted(project, settings, monkeypatch):
    monkeypatch.setattr(CodeAgent, "max_finish_reviews", 1)
    router = _ScriptedRouter(
        _resp(_call("c1", "finish", summary="Hola, ¿en que te ayudo?")),
        _resp(_call("c2", "finish", summary="Hola, ¿en que te ayudo?")),
    )

    result = await _agent(router, settings).propose("ctx", "hola", workspace=str(project))

    assert result["summary"] == "Hola, ¿en que te ayudo?" and len(router.seen) == 2


@pytest.mark.asyncio
async def test_a_finish_after_reading_files_is_accepted_immediately(project, settings, monkeypatch):
    monkeypatch.setattr(CodeAgent, "max_finish_reviews", 1)
    router = _ScriptedRouter(
        _resp(_call("c1", "read_file", path="src/app.py")),
        _resp(_call("c2", "finish", summary="saluda devuelve 'hola' (src/app.py:2)")),
    )

    await _agent(router, settings).propose("ctx", "explica app.py", workspace=str(project))

    assert len(router.seen) == 2


# ── Buscador de codigo y pre-carga de evidencia ──────────────────────────────

@pytest.mark.asyncio
async def test_the_harness_prefetches_candidates_before_the_first_model_call(project, settings, monkeypatch):
    monkeypatch.setattr(CodeAgent, "prefetch_hits", 8)          # opt-in: apagada por defecto
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))

    await _agent(router, settings).propose("ctx", "¿donde esta la funcion saluda?", workspace=str(project))

    first = router.seen[0]
    assert [m["role"] for m in first[-3:]] == ["user", "assistant", "tool"]            # tarea, find_code "pedido", resultado
    assert first[-2]["tool_calls"][0]["function"]["name"] == "find_code"
    prefetch = first[-1]["content"]
    assert first[-1]["tool_call_id"] == "prefetch_1"
    assert "src/app.py:1" in prefetch and "saluda" in prefetch
    assert "pueden NO ser los correctos" in prefetch


@pytest.mark.asyncio
async def test_prefetch_does_not_count_as_having_looked_so_the_model_must_still_read(project, settings, monkeypatch):
    monkeypatch.setattr(CodeAgent, "prefetch_hits", 8)
    monkeypatch.setattr(CodeAgent, "max_finish_reviews", 1)
    router = _ScriptedRouter(
        _resp(_call("c1", "finish", summary="saluda esta por ahi")),
        _resp(_call("c2", "read_file", path="src/app.py")),
        _resp(_call("c3", "finish", summary="saluda esta en src/app.py:1")),
    )

    result = await _agent(router, settings).propose("ctx", "¿donde esta saluda?", workspace=str(project))

    assert result["summary"] == "saluda esta en src/app.py:1"
    assert "No has consultado ningun fichero" in _tool_result(router.seen[1], "c1")    # la pre-carga no valio como lectura


@pytest.mark.asyncio
async def test_the_model_can_search_again_with_find_code_and_english_keywords(project, settings):
    (project / "src" / "otro.py").write_text("def notify_watcher():\n    # avisa al vigilante\n    return 1\n", encoding="utf-8")
    router = _ScriptedRouter(
        _resp(_call("c1", "find_code", question="centinela de avisos", keywords=["notify", "watcher"])),
        _resp(_call("c2", "finish", summary="en src/otro.py:1")),
    )

    await _agent(router, settings).propose("ctx", "¿quien avisa al centinela?", workspace=str(project))

    assert "src/otro.py:1" in _tool_result(router.seen[1], "c1")


@pytest.mark.asyncio
async def test_find_code_without_a_question_or_without_results_explains_itself(project, settings):
    router = _ScriptedRouter(
        _resp(_call("c1", "find_code", question="  "), _call("c2", "find_code", question="zzqqxx")),
        _resp(_call("c3", "finish", summary="nada")),
    )

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    assert "Falta la pregunta" in _tool_result(router.seen[1], "c1")
    assert "Sin resultados" in _tool_result(router.seen[1], "c2")


@pytest.mark.asyncio
async def test_no_prefetch_when_nothing_matches(project, settings, monkeypatch):
    monkeypatch.setattr(CodeAgent, "prefetch_hits", 8)
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))

    await _agent(router, settings).propose("ctx", "zzqqxx", workspace=str(project))

    assert [m["role"] for m in router.seen[0]] == ["system", "user"]


@pytest.mark.asyncio
async def test_the_index_is_reused_between_questions_and_picks_up_changes(project, settings):
    agent = _agent(_ScriptedRouter(), settings)
    ws = agent._open_workspace(str(project))

    first = await asyncio.to_thread(agent._index_for, ws)
    (project / "src" / "nuevo.py").write_text("def purgar_cache():\n    return 1\n", encoding="utf-8")
    second = await asyncio.to_thread(agent._index_for, ws)

    assert first is second
    assert any(c.name == "purgar_cache" for c in second._chunks)


def test_the_prefetched_evidence_is_the_last_thing_to_be_elided(tmp_path):
    agent = _agent_with_default_quota(tmp_path)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"},
                {"role": "tool", "tool_call_id": "prefetch_1", "content": "P" * 6_000}]
    for i in range(4):
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 6_000})

    agent._prepare_messages(messages)

    contents = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
    assert contents["prefetch_1"] == "P" * 6_000                                       # se conserva
    assert contents["c0"].startswith("[resultado antiguo omitido")                     # se omite lo demas, antes


def test_find_code_is_offered_to_the_model():
    names = [t["function"]["name"] for t in CodeAgent.tools]

    assert "find_code" in names and "read_file" in names


@pytest.mark.asyncio
async def test_prefetch_is_off_by_default_because_it_made_the_agent_worse(project, settings):
    """Medido el 2026-10-20 con qwen3:8b (12 preguntas no usadas para afinar): con pre-carga 5/12 y 4/12 correctas,
    sin ella 9/12. El modelo se ancla en los candidatos y termina antes con respuestas mas flojas."""
    assert CodeAgent.prefetch_hits == 0
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="ok")))

    await _agent(router, settings).propose("ctx", "¿donde esta la funcion saluda?", workspace=str(project))

    assert [m["role"] for m in router.seen[0]] == ["system", "user"]         # sin pre-carga
    assert "find_code" in [t["function"]["name"] for t in CodeAgent.tools]  # pero la herramienta sigue ahi


@pytest.mark.asyncio
async def test_find_code_returns_find_code_hits_candidates(project, settings, monkeypatch):
    for i in range(12):
        (project / "src" / f"mod{i}.py").write_text(f"def saluda_{i}():\n    return 'hola'\n", encoding="utf-8")
    monkeypatch.setattr(CodeAgent, "find_code_hits", 3)
    router = _ScriptedRouter(_resp(_call("c1", "find_code", question="saluda hola")), _resp(_call("c2", "finish", summary="x")))

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    result = _tool_result(router.seen[1], "c1")
    assert result.count(".py:") <= 4                                      # 3 candidatos (+ posibles lineas de codigo)
    assert "1." in result and "3." in result and "4. " not in result


# ── grep sin resultados -> candidatos de find_code ───────────────────────────

@pytest.mark.asyncio
async def test_a_grep_without_matches_gets_find_code_candidates_attached(project, settings):
    """Visto en vivo: el modelo hizo grep "token limit" y "rate limit" sin usar find_code (pese a la regla
    del prompt). El resultado de la herramienta SI se lee: se le adjuntan candidatos."""
    (project / "src" / "cuota.py").write_text(
        "def aplicar_limite_tokens():\n    # limita los tokens por minuto\n    return 1\n", encoding="utf-8"
    )
    router = _ScriptedRouter(
        _resp(_call("c1", "grep", pattern="token limit")),
        _resp(_call("c2", "finish", summary="x")),
    )

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    result = _tool_result(router.seen[1], "c1")
    assert result.startswith("Sin coincidencias")
    assert "find_code" in result and "src/cuota.py:1" in result


@pytest.mark.asyncio
async def test_a_grep_with_matches_is_left_untouched(project, settings):
    router = _ScriptedRouter(_resp(_call("c1", "grep", pattern="def saluda")), _resp(_call("c2", "finish", summary="x")))

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    result = _tool_result(router.seen[1], "c1")
    assert "src/app.py:1" in result and "find_code" not in result


@pytest.mark.asyncio
async def test_a_grep_without_matches_and_nothing_to_suggest_stays_plain(project, settings):
    router = _ScriptedRouter(_resp(_call("c1", "grep", pattern="zzqqxx")), _resp(_call("c2", "finish", summary="x")))

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    assert _tool_result(router.seen[1], "c1") == "Sin coincidencias."


# ── llamadas repetidas ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_third_identical_call_is_not_executed_and_nudges_the_model(project, settings):
    """Visto en vivo: qwen3:8b repitio la misma lectura 9 veces hasta agotar los 10 minutos."""
    same = lambda cid: _call(cid, "read_file", path="src/app.py", start_line=1, end_line=2)   # noqa: E731
    router = _ScriptedRouter(
        _resp(same("c1")), _resp(same("c2")), _resp(same("c3")), _resp(_call("c4", "finish", summary="x")),
    )

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    last = router.seen[3]
    assert "def saluda" in _tool_result(last, "c1")
    assert "def saluda" in _tool_result(last, "c2")           # una relectura es legitima
    nudge = _tool_result(last, "c3")
    assert "def saluda" not in nudge and "finish" in nudge and "find_code" in nudge


@pytest.mark.asyncio
async def test_a_reversed_range_counts_as_the_same_call(project, settings):
    router = _ScriptedRouter(
        _resp(_call("c1", "read_file", path="src/app.py", start_line=2, end_line=1)),
        _resp(_call("c2", "read_file", path="src/app.py", start_line=1, end_line=2)),
        _resp(_call("c3", "read_file", path="src/app.py", start_line=2, end_line=1)),
        _resp(_call("c4", "finish", summary="x")),
    )

    await _agent(router, settings).propose("ctx", "pregunta", workspace=str(project))

    assert "def saluda" not in _tool_result(router.seen[3], "c3")


@pytest.mark.asyncio
async def test_repeats_are_counted_per_task_not_across_tasks(project, settings):
    router = _ScriptedRouter(
        *[_resp(_call(f"a{i}", "read_file", path="src/app.py")) for i in range(2)], _resp(_call("a9", "finish", summary="x")),
        *[_resp(_call(f"b{i}", "read_file", path="src/app.py")) for i in range(2)], _resp(_call("b9", "finish", summary="x")),
    )
    agent = _agent(router, settings)

    await agent.propose("ctx", "pregunta", workspace=str(project))
    await agent.propose("ctx2", "otra", workspace=str(project))

    for seen in router.seen[3:]:
        assert all("Ya hiciste" not in str(m.get("content")) for m in seen)


# ── Recorrido (tour) ─────────────────────────────────────────────────────────

@pytest.fixture
def tour_project(tmp_path, settings):
    root = tmp_path / "programa"
    (root / "core").mkdir(parents=True)
    (root / "main.py").write_text('"""Arranque del programa."""\n\n\ndef main():\n    return 1\n', encoding="utf-8")
    (root / "core" / "parser.py").write_text("def parsear():\n    return 2\n", encoding="utf-8")
    (root / "core" / "indexer.py").write_text("def indexar():\n    return 3\n", encoding="utf-8")
    settings.add_workspace(str(root))
    return root


TOUR_QUESTION = "Haz un recorrido por este programa y dime que parece ser"


@pytest.mark.asyncio
async def test_a_tour_gets_a_real_map_of_the_project_in_the_system_prompt(tour_project, settings):
    router = _ScriptedRouter(*[_resp(_call(f"c{i}", "finish", summary="x")) for i in range(4)])   # 3 revisiones + aceptar

    await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    system = router.seen[0][0]["content"]
    assert "MODO RECORRIDO" in system and "MAPA DEL PROYECTO" in system
    assert "main.py" in system and "core/parser.py" in system and "parsear:1" in system


@pytest.mark.asyncio
async def test_a_specific_question_gets_no_map(project, settings):
    router = _ScriptedRouter(_resp(_call("c1", "finish", summary="x")))

    await _agent(router, settings).propose("ctx", "¿donde esta saluda?", workspace=str(project))

    assert "MAPA DEL PROYECTO" not in router.seen[0][0]["content"]


@pytest.mark.asyncio
async def test_a_tour_cannot_finish_without_opening_files_nor_skipping_modules(tour_project, settings):
    """Medido: el modelo leyo 1 fichero de 16 y describio solo ese."""
    router = _ScriptedRouter(
        _resp(_call("c1", "finish", summary="Parece un programa. main.py:4")),                       # 0 ficheros abiertos
        _resp(*[_call(f"r{i}", "read_file", path=p) for i, p in enumerate(("main.py", "core/parser.py", "core/indexer.py"))]),
        _resp(_call("c2", "finish", summary="`main.py:4` arranca y `core/parser.py:1` parsea.")),   # falta indexer.py
        _resp(_call("c3", "finish", summary="main.py:4 arranca; core/parser.py:1 parsea; core/indexer.py:1 indexa.")),
    )

    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    assert "has abierto 0 fichero" in _tool_result(router.seen[1], "c1")
    missing = _tool_result(router.seen[3], "c2")
    assert "no nombra estos modulos" in missing and "core/indexer.py" in missing and "main.py" not in missing
    assert result["kind"] == "finish" and "core/indexer.py:1 indexa" in result["summary"]


@pytest.mark.asyncio
async def test_a_finished_tour_says_which_files_were_never_opened(tour_project, settings):
    router = _ScriptedRouter(
        _resp(*[_call(f"r{i}", "read_file", path=p) for i, p in enumerate(("main.py", "core/parser.py", "core/indexer.py"))]),
        _resp(_call("c1", "finish", summary="main.py:4 arranca; core/parser.py:1 parsea; core/indexer.py:1 indexa.")),
    )

    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    assert "Leidos a fondo: main.py, core/indexer.py, core/parser.py." in result["summary"] and "NO abiertos" not in result["summary"]


@pytest.mark.asyncio
async def test_the_footer_lists_unopened_files_when_the_reviews_run_out(tour_project, settings):
    router = _ScriptedRouter(
        *[_resp(_call(f"f{i}", "finish", summary="Solo main.py:4")) for i in range(4)],
    )
    # El modelo insiste en su respuesta incompleta: agotadas las 3 revisiones se acepta, pero el pie avisa.
    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    summary = result["summary"]
    assert summary.startswith("Solo main.py:4")
    assert "NO abiertos" in summary and "core/parser.py" in summary and "deduccion" in summary


@pytest.mark.asyncio
async def test_tour_state_does_not_leak_into_the_next_question(tour_project, settings):
    router = _ScriptedRouter(
        _resp(_call("a1", "finish", summary="x")), _resp(_call("a2", "finish", summary="x")), _resp(_call("a3", "finish", summary="x")),
        _resp(_call("a4", "finish", summary="x")),
        _resp(_call("b1", "finish", summary="x")),
    )
    agent = _agent(router, settings)
    await agent.propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    result = await agent.propose("ctx2", "¿donde esta parsear?", workspace=str(tour_project))

    assert result["summary"] == "x"          # sin pie de cobertura


@pytest.fixture
def with_notes(monkeypatch):
    """Las notas por modulo solo se piden con modelo propio; aqui se fuerzan con un router simulado."""
    monkeypatch.setattr(CodeAgent, "_use_notes", lambda self: True)


@pytest.mark.asyncio
async def test_each_module_gets_a_note_and_the_harness_asks_for_the_synthesis(tour_project, settings, with_notes):
    """Medido: dejando al modelo navegar, hizo 21 find_code sin abrir un fichero; con las notas delante siguio
    explorando. El arnes lee, pide una nota por modulo y luego UNA sintesis sin herramientas (sin bucle)."""
    router = _ScriptedRouter(
        _resp(content="Arranca el programa. `main` (L4)."),
        _resp(content="Indexa. `indexar` (L1)."),
        _resp(content="Parsea ficheros. `parsear` (L1)."),
        _resp(content="Es un programa pequeño.\n- `main.py`: arranca.\n- `core/indexer.py`: indexa.\n- `core/parser.py`: parsea."),
    )

    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    note_call = router.seen[1]                                     # nota de un modulo: sin herramientas, solo su cabecera
    assert note_call[0]["role"] == "system" and "resume UN modulo" in note_call[0]["content"]
    assert "INICIO DEL FICHERO" in note_call[1]["content"] and "def " in note_call[1]["content"]
    synthesis = router.seen[3]
    assert "NOTAS POR MODULO" in synthesis[1]["content"] and "Arranca el programa" in synthesis[1]["content"]
    assert "Parsea ficheros" in synthesis[1]["content"] and TOUR_QUESTION in synthesis[1]["content"]
    assert result["kind"] == "finish" and result["summary"].startswith("Es un programa pequeño.")
    assert "no menciona" not in result["summary"]                  # la sintesis nombro todos los modulos
    assert "Resumidos a partir de su esquema" in result["summary"] and "NO abiertos" not in result["summary"]


@pytest.mark.asyncio
async def test_modules_the_synthesis_forgets_are_added_by_the_harness_with_their_note(tour_project, settings, with_notes):
    router = _ScriptedRouter(
        _resp(content="Arranca."), _resp(content="Indexa documentos."), _resp(content="Parsea ficheros."),
        _resp(content="Es un programa. `main.py` arranca y `core/parser.py` parsea."),          # olvida core/indexer.py
    )

    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    assert "Modulos que la explicacion anterior no menciona:" in result["summary"]
    assert "- `core/indexer.py` (2 lin.): Indexa documentos." in result["summary"]
    assert "- `main.py`" not in result["summary"].split("no menciona:")[1]


@pytest.mark.asyncio
async def test_if_the_synthesis_fails_the_user_gets_the_notes_themselves(tour_project, settings, with_notes):
    router = _ScriptedRouter(
        _resp(content="Arranca."), _resp(content="Indexa."), _resp(content="Parsea."),
        SimpleNamespace(error="ollama_error | boom", content="", tool_calls=None),
    )

    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    assert result["summary"].startswith("No pude redactar la sintesis")
    assert "- main.py (5 lin.): Arranca." in result["summary"] and "- core/parser.py (2 lin.): Parsea." in result["summary"]


@pytest.mark.asyncio
async def test_a_failing_note_stops_the_notes_but_the_rest_still_gets_a_synthesis(tour_project, settings, with_notes):
    router = _ScriptedRouter(
        _resp(content="Arranca."),
        SimpleNamespace(error="ollama_error | boom", content="", tool_calls=None),
        _resp(content="Es un programa. `main.py` arranca."),
    )

    result = await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    notes = router.seen[2][1]["content"]
    assert "- main.py (5 lin.): Arranca." in notes and "sin resumir" in notes
    assert "no menciona" in result["summary"] and "core/parser.py" in result["summary"]      # el arnes los anade
    assert "NO abiertos" in result["summary"]                                                # y se reconocen como deduccion


@pytest.mark.asyncio
async def test_notes_are_not_requested_without_an_own_model(tour_project, settings):
    router = _ScriptedRouter(*[_resp(_call(f"c{i}", "finish", summary="x")) for i in range(4)])

    await _agent(router, settings).propose("ctx", TOUR_QUESTION, workspace=str(tour_project))

    assert "NOTAS POR MODULO" not in router.seen[0][0]["content"] and "MAPA DEL PROYECTO" in router.seen[0][0]["content"]
