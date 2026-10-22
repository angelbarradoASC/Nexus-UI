"""tests/unit/test_code_citations.py

Verificador de citas del agente de codigo. Medido el 2026-10-20 con qwen3:8b: la mitad de las
respuestas a preguntas nuevas señalaban el fichero correcto pero sin linea, y otras citaban
lineas reales pero equivocadas. El arnes exige citas verificables antes de aceptar la respuesta.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.code_agent.agent import CodeAgent
from desktop.code_agent.citations import citations, verify_citations
from desktop.code_agent.workspace import Workspace
from desktop.storage.code_settings import CodeSettingsStore


@pytest.fixture
def ws(tmp_path) -> Workspace:
    root = tmp_path / "proyecto"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "app.py").write_text("\n".join(f"linea {i}" for i in range(1, 41)), encoding="utf-8")   # 40 lineas
    (root / "src" / "pkg" / "util.py").write_text("a\nb\nc\n", encoding="utf-8")
    (root / "src" / "pkg" / "otro" ).mkdir()
    (root / "src" / "pkg" / "otro" / "util.py").write_text("x\n", encoding="utf-8")
    (root / ".env").write_text("SECRETO=1\n", encoding="utf-8")
    return Workspace(root)


SEEN = "src/app.py (lineas 1-40)\n   1\tlinea 1\nsrc/pkg/util.py:1: a"


# ── Extraccion ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("En `src/app.py:12` esta.", [("src/app.py", 12, 12)]),
    ("Entre src/app.py:10-20 y src\\pkg\\util.py:2", [("src/app.py", 10, 20), ("src/pkg/util.py", 2, 2)]),
    ("En app.py#L7 (GitHub)", [("app.py", 7, 7)]),
    ("Python 3.11 y version 2.5: sin citas", []),
])
def test_citations_are_extracted(text, expected):
    assert citations(text) == expected


# ── Verificacion ─────────────────────────────────────────────────────────────

def test_a_valid_citation_to_a_file_the_model_has_seen_passes(ws):
    valid, problems = verify_citations("Esta en src/app.py:12.", ws, SEEN)

    assert valid == [("src/app.py", 12, 12)] and problems == []


def test_a_range_inside_the_file_passes_and_one_past_the_end_fails(ws):
    assert verify_citations("src/app.py:30-40", ws, SEEN)[1] == []
    problems = verify_citations("src/app.py:30-99", ws, SEEN)[1]

    assert len(problems) == 1 and "solo tiene 40 lineas" in problems[0]


def test_a_line_past_the_end_or_zero_is_rejected(ws):
    assert "solo tiene 40 lineas" in verify_citations("src/app.py:437", ws, SEEN)[1][0]
    assert verify_citations("src/app.py:0", ws, SEEN)[1]


def test_a_file_that_does_not_exist_is_rejected(ws):
    problems = verify_citations("Mira src/fantasma.py:3", ws, SEEN)[1]

    assert len(problems) == 1 and "no existe" in problems[0]


def test_a_real_file_the_model_never_saw_is_rejected(ws):
    """Evita citar de memoria ficheros que nunca se abrieron en la tarea."""
    problems = verify_citations("src/pkg/util.py:2", ws, "solo se vio src/app.py")[1]

    assert len(problems) == 1 and "no has visto ese fichero" in problems[0]


def test_seen_is_checked_case_insensitively_and_by_file_name(ws):
    assert verify_citations("src/pkg/util.py:2", ws, "SRC\\PKG\\UTIL.PY aparecio")[1] == []
    assert verify_citations("src/pkg/util.py:2", ws, "leyo util.py")[1] == []


def test_a_bare_file_name_is_accepted_only_if_it_is_unambiguous(ws):
    known = lambda: ["src/app.py", "src/pkg/util.py", "src/pkg/otro/util.py"]

    assert verify_citations("app.py:5", ws, SEEN, known)[0] == [("src/app.py", 5, 5)]
    ambiguous = verify_citations("util.py:1", ws, SEEN, known)[1]
    assert len(ambiguous) == 1 and "ambiguo" in ambiguous[0]


def test_protected_files_cannot_be_cited_even_if_they_exist(ws):
    (ws.root / "src" / ".env").write_text("SECRETO=1\n", encoding="utf-8")

    problems = verify_citations("src/.env:1", ws, SEEN + "\nsrc/.env")[1]

    assert problems and "no existe" in problems[0]


def test_paths_outside_the_workspace_are_rejected(ws):
    assert verify_citations("../fuera.py:1", ws, SEEN)[1]
    assert verify_citations("C:/Windows/win.ini:1", ws, SEEN)[1]


def test_only_a_bounded_number_of_citations_is_checked(ws):
    many = " ".join(f"src/app.py:{i}" for i in range(1, 40))

    valid, problems = verify_citations(many, ws, SEEN)

    assert len(valid) + len(problems) <= 12


# ── Dentro del agente ────────────────────────────────────────────────────────

def _call(call_id, name, **args):
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}


def _resp(*calls, content=None):
    return SimpleNamespace(error=None, content=content, tool_calls=list(calls) or None)


class _Router:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.seen = []

    async def call(self, messages, **kwargs):
        self.seen.append(json.loads(json.dumps(messages)))
        return self._responses.pop(0)


@pytest.fixture
def agent_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(CodeAgent, "tokens_per_minute", 10**9)
    root = tmp_path / "p"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def saluda():\n    return 'hola'\n", encoding="utf-8")
    settings = CodeSettingsStore(tmp_path / "s.json")
    settings.add_workspace(str(root))
    settings.set_tokens_per_minute(1_000_000)
    return root, settings


def _tool(messages, call_id):
    return dict((m["tool_call_id"], m["content"]) for m in messages if m.get("role") == "tool")[call_id]


@pytest.mark.asyncio
async def test_an_answer_without_a_line_citation_is_sent_back_once(agent_setup):
    root, settings = agent_setup
    router = _Router(
        _resp(_call("c1", "read_file", path="src/app.py")),
        _resp(_call("c2", "finish", summary="saluda esta en src/app.py")),               # fichero pero SIN linea
        _resp(_call("c3", "finish", summary="saluda esta en src/app.py:1")),
    )

    result = await CodeAgent(None, llm_router=router, settings=settings).propose("ctx", "¿donde esta saluda?", workspace=str(root))

    assert result["summary"] == "saluda esta en src/app.py:1"
    assert "no cita ninguna ruta:linea" in _tool(router.seen[2], "c2")


@pytest.mark.asyncio
async def test_an_invented_line_is_sent_back_with_the_reason(agent_setup):
    root, settings = agent_setup
    router = _Router(
        _resp(_call("c1", "read_file", path="src/app.py")),
        _resp(_call("c2", "finish", summary="saluda esta en src/app.py:437")),
        _resp(_call("c3", "finish", summary="saluda esta en src/app.py:2")),
    )

    result = await CodeAgent(None, llm_router=router, settings=settings).propose("ctx", "¿donde esta saluda?", workspace=str(root))

    assert result["summary"] == "saluda esta en src/app.py:2"
    objection = _tool(router.seen[2], "c2")
    assert "no son verificables" in objection and "solo tiene 2 lineas" in objection


@pytest.mark.asyncio
async def test_a_file_cited_from_memory_is_sent_back(agent_setup):
    root, settings = agent_setup
    (root / "src" / "otro.py").write_text("def otro():\n    pass\n", encoding="utf-8")
    router = _Router(
        _resp(_call("c1", "read_file", path="src/app.py")),
        _resp(_call("c2", "finish", summary="esta en src/otro.py:1")),                   # nunca lo abrio
        _resp(_call("c3", "read_file", path="src/otro.py")),
        _resp(_call("c4", "finish", summary="esta en src/otro.py:1")),
    )

    result = await CodeAgent(None, llm_router=router, settings=settings).propose("ctx", "¿donde?", workspace=str(root))

    assert result["summary"] == "esta en src/otro.py:1"
    assert "no has visto ese fichero" in _tool(router.seen[2], "c2")


@pytest.mark.asyncio
async def test_if_the_model_insists_the_answer_is_accepted_after_the_reviews(agent_setup):
    root, settings = agent_setup
    router = _Router(
        _resp(_call("c1", "read_file", path="src/app.py")),
        _resp(_call("c2", "finish", summary="sin cita")),
        _resp(_call("c3", "finish", summary="sin cita")),
        _resp(_call("c4", "finish", summary="sin cita")),
    )

    result = await CodeAgent(None, llm_router=router, settings=settings).propose("ctx", "¿donde?", workspace=str(root))

    assert result["summary"] == "sin cita"
    assert len(router.seen) == 4                       # 2 rechazos y a la tercera se acepta
    assert CodeAgent.max_finish_reviews == 2


# ── Rangos acotados y funcion citada en su sitio ─────────────────────────────

def test_a_range_wider_than_the_limit_is_rejected(ws):
    """Visto en vivo: un recorrido citaba tramos de 60-100 lineas que eran lo que el modelo habia leido."""
    (ws.root / "src" / "largo.py").write_text("\n".join("x" for _ in range(300)), encoding="utf-8")

    valid, problems = verify_citations("Mira `src/largo.py:100-199`.", ws, "src/largo.py")

    assert not valid and "demasiado ancho" in problems[0] and "100 lineas" in problems[0]


def test_a_range_at_the_limit_is_accepted(ws):
    (ws.root / "src" / "largo.py").write_text("\n".join("x" for _ in range(300)), encoding="utf-8")

    valid, problems = verify_citations("`src/largo.py:100-159`", ws, "src/largo.py")

    assert valid == [("src/largo.py", 100, 159)] and not problems


SYMBOLS = {"src/app.py": [("saluda", 10, 14), ("Servicio", 20, 35), ("Servicio.corre", 22, 30)]}


def test_a_named_function_outside_the_cited_lines_is_flagged(ws):
    valid, problems = verify_citations(
        "`saluda` esta en `src/app.py:30`.", ws, SEEN, symbols_of=lambda path: SYMBOLS.get(path, []),
    )

    assert not valid
    assert "`saluda` esta definida en src/app.py:10-14" in problems[0]


def test_a_named_function_inside_the_cited_lines_passes(ws):
    answer = "`saluda` esta en `src/app.py:12`.\nEl metodo `corre` en `src/app.py:25-28`."

    valid, problems = verify_citations(answer, ws, SEEN, symbols_of=lambda path: SYMBOLS.get(path, []))

    assert len(valid) == 2 and not problems


def test_a_name_that_is_not_defined_in_that_file_is_not_second_guessed(ws):
    valid, problems = verify_citations(
        "`otra_cosa` en `src/app.py:30`.", ws, SEEN, symbols_of=lambda path: SYMBOLS.get(path, []),
    )

    assert valid and not problems


def test_symbols_are_not_checked_when_a_line_has_several_citations(ws):
    valid, problems = verify_citations(
        "`saluda` en `src/app.py:30` y `src/pkg/util.py:1`.", ws, SEEN, symbols_of=lambda path: SYMBOLS.get(path, []),
    )

    assert len(valid) == 2 and not problems
