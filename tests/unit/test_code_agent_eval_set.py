"""tests/unit/test_code_agent_eval_set.py

Conjunto de preguntas de prueba del agente de codigo (tests/eval/*.json) y su correccion.

- Integridad: cada simbolo esperado EXISTE hoy en el repo. Si alguien renombra o borra una de esas
  funciones, este test falla y avisa de que hay que actualizar el conjunto (no se degrada en silencio).
- Regresion del buscador sobre este mismo repo, con umbrales por debajo de lo medido (2026-10-20:
  recall@8 = 0,95 en dev+holdout y 0,58 en las preguntas frescas) para no ser fragil.
- La correccion de respuestas (`grade_answer`) y la extraccion de citas, con casos sinteticos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from desktop.code_agent import evaluation as ev
from desktop.code_agent.index import CodeIndex
from desktop.code_agent.workspace import Workspace

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "tests" / "eval"


@pytest.fixture(scope="module")
def repo_index():
    index = CodeIndex(Workspace(ROOT), exclude_prefixes=("tests/eval/",))
    index.refresh()
    return index


def _all_questions():
    return ev.load_questions(EVAL_DIR / "code_questions.json") + ev.load_questions(EVAL_DIR / "code_questions_fresh.json")


# ── Integridad del conjunto ──────────────────────────────────────────────────

def test_the_eval_files_are_well_formed():
    questions = _all_questions()

    assert len(questions) >= 30
    assert len({q.id for q in questions}) == len(questions)            # ids unicos
    assert {q.split for q in questions} == {"dev", "holdout", "fresh"}
    for q in questions:
        assert q.question.strip().endswith("?") and q.expect


def test_every_expected_symbol_still_exists_in_the_repo(repo_index):
    missing = [
        f"{q.id}: {r['path']} :: {r['symbol']}"
        for q in _all_questions()
        for r in ev.resolve_symbols(repo_index, q.expect)
        if r["start"] is None
    ]

    assert missing == [], "Simbolos esperados que ya no existen (actualiza tests/eval): " + "; ".join(missing)


def test_questions_do_not_leak_the_answer_through_identifiers():
    """Las preguntas se redactan como un usuario: sin nombres de funciones ni de ficheros."""
    for q in _all_questions():
        for expected in q.expect:
            symbol = expected["symbol"].split(".")[-1]
            assert symbol.lower() not in q.question.lower(), f"{q.id} contiene el simbolo {symbol}"
            assert Path(expected["path"]).name not in q.question, f"{q.id} contiene el nombre del fichero"


# ── Regresion del buscador ───────────────────────────────────────────────────

def test_retrieval_does_not_regress_on_this_repo(repo_index):
    results = ev.retrieval_report(repo_index, _all_questions(), k=8)
    summary = ev.summarize_retrieval(results, k=8)

    assert summary["dev"]["recall@8"] >= 0.9
    assert summary["holdout"]["recall@8"] >= 0.8
    fresh = ev.summarize_retrieval([r for r in results if r.split == "fresh"], k=8)["all"]
    assert fresh["recall@8"] >= 0.5                                    # preguntas que no se usaron para afinar


def test_the_question_files_themselves_are_not_indexed_in_eval_mode(repo_index):
    assert not any(c.path.startswith("tests/eval/") for c in repo_index._chunks)


# ── Citas y correccion ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Esta en desktop/runtime/skill_router.py:190.", [("desktop/runtime/skill_router.py", 190, 190)]),
    ("Ver `app/main.py:10-24` y tambien tests\\unit\\a.py:5", [("app/main.py", 10, 24), ("tests/unit/a.py", 5, 5)]),
    ("En el fichero skill_router.py#L190 se decide", [("skill_router.py", 190, 190)]),
    ("Sin citas aqui. Version 3.11 de Python.", []),
    ("", []),
])
def test_citations_are_extracted(text, expected):
    assert ev.citations(text) == expected


RESOLVED = [{"path": "desktop/runtime/skill_router.py", "symbol": "DesktopSkillRouter.resolve_llm", "start": 164, "end": 210}]


def test_a_citation_inside_the_expected_symbol_is_correct():
    graded = ev.grade_answer("Se decide en desktop/runtime/skill_router.py:190 dentro de resolve_llm.", RESOLVED)

    assert graded["grade"] == "correcta"


def test_a_citation_with_a_small_slack_or_a_path_suffix_is_still_correct():
    assert ev.grade_answer("skill_router.py:162", RESOLVED)["grade"] == "correcta"                 # solo el nombre del fichero + holgura de 3
    assert ev.grade_answer("runtime/skill_router.py:166-170", RESOLVED)["grade"] == "correcta"     # sufijo de ruta y rango
    assert ev.grade_answer("desktop/runtime/skill_router.py:213", RESOLVED)["grade"] == "correcta"  # fin + holgura de 3


def test_right_file_wrong_line_or_only_the_symbol_name_is_partial():
    assert ev.grade_answer("Esta en desktop/runtime/skill_router.py:400.", RESOLVED)["grade"] == "parcial"
    assert ev.grade_answer("Lo hace la funcion resolve_llm.", RESOLVED)["grade"] == "parcial"


def test_a_different_file_or_no_citation_is_incorrect():
    assert ev.grade_answer("Esta en app/agents/orchestration_agent.py:125.", RESOLVED)["grade"] == "incorrecta"
    assert ev.grade_answer("No lo se.", RESOLVED)["grade"] == "incorrecta"
    assert ev.grade_answer("", RESOLVED)["grade"] == "incorrecta"


def test_symbols_that_no_longer_exist_never_grade_as_correct():
    stale = [{"path": "x.py", "symbol": "borrada", "start": None, "end": None}]

    assert ev.grade_answer("x.py:1", stale)["grade"] != "correcta"


def test_summarize_retrieval_splits_by_set_and_computes_mrr():
    results = [
        ev.RetrievalResult("a", "dev", 1), ev.RetrievalResult("b", "dev", 2),
        ev.RetrievalResult("c", "holdout", None), ev.RetrievalResult("d", "holdout", 4),
    ]

    summary = ev.summarize_retrieval(results, k=5)

    assert summary["all"]["recall@5"] == 0.75
    assert summary["dev"]["mrr"] == pytest.approx((1 + 0.5) / 2)
    assert summary["holdout"]["recall@5"] == 0.5
