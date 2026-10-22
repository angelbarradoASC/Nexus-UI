"""tests/unit/test_code_tour.py

Recorrido de un proyecto (desktop/code_agent/tour.py). Medido el 2026-10-22: ante "haz un recorrido por
este programa" qwen3:8b leyo UN fichero de 16 y describio solo ese. La cobertura la decide el arnes.
"""

from __future__ import annotations

import pytest

from desktop.code_agent.index import CodeIndex
from desktop.code_agent.tour import (
    build_outlines,
    coverage_footer,
    coverage_units,
    clean_note,
    format_map,
    format_notes,
    is_tour_question,
    missing_units,
    module_input,
)
from desktop.code_agent.workspace import Workspace


@pytest.fixture
def project(tmp_path) -> Workspace:
    root = tmp_path / "proyecto"
    (root / "src" / "core").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "main.py").write_text('"""\nmain.py\n-------\nPunto de entrada de Proyecto.\n"""\n\n\ndef main():\n    return 1\n', encoding="utf-8")
    (root / "src" / "core" / "parser.py").write_text(
        '"""Lee ficheros exportados."""\n\n\nclass Mensaje:\n    def a(self):\n        pass\n\n    def b(self):\n        pass\n\n\ndef parsear():\n    pass\n\n\ndef _privada():\n    pass\n',
        encoding="utf-8",
    )
    (root / "src" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "core" / "datos.py").write_text("X = 1\n", encoding="utf-8")                    # sin funciones ni docstring
    (root / "tests" / "test_parser.py").write_text("def test_parsear():\n    assert True\n", encoding="utf-8")
    return Workspace(root)


@pytest.fixture
def outlines(project):
    index = CodeIndex(project)
    index.refresh()
    return build_outlines(index)


# ── Deteccion ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "Haz un recorrido por este programa y dime que es lo qeu parece ser",
    "Recorre el proyecto y explicamelo",
    "revisa el programa",
    "Repasa este codigo",
    "¿Qué hace este proyecto?",
    "Dame una visión general del código",
    "explicame el programa",
])
def test_overview_requests_are_tours(question):
    assert is_tour_question(question)


@pytest.mark.parametrize("question", [
    "Donde se limita cuantos tokens por minuto puede gastar el agente?",
    "¿Qué hace la función parsear?",
    "En que fichero se guardan las carpetas autorizadas",
    "revisa el fichero parser.py",
    "",
])
def test_specific_questions_are_not_tours(question):
    assert not is_tour_question(question)


# ── Mapa ─────────────────────────────────────────────────────────────────────

def test_the_map_lists_real_files_functions_and_lines(outlines):
    text = format_map(outlines)

    assert "main.py (9 lin.) [punto de entrada] — Punto de entrada de Proyecto." in text       # salta la ruta y las rayas
    assert "src/core/parser.py" in text and "Mensaje:4 (2 metodos)" in text and "parsear:12" in text
    assert "datos.py" not in text and "__init__" not in text                                    # sin codigo: fuera
    assert "test_parser" not in text and "1 ficheros de tests" in text


def test_entry_points_come_first_and_only_at_the_root(tmp_path):
    root = tmp_path / "p"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "app.py").write_text("def a():\n    pass\n", encoding="utf-8")
    (root / "z_main.py").write_text("def z():\n    pass\n", encoding="utf-8")
    (root / "main.py").write_text("def m():\n    pass\n", encoding="utf-8")
    index = CodeIndex(Workspace(root))
    index.refresh()

    ordered = [o.path for o in build_outlines(index)]

    assert ordered[0] == "main.py"
    assert not next(o for o in build_outlines(index) if o.path == "sub/app.py").is_entry


def test_the_map_degrades_to_fit_its_budget(tmp_path):
    root = tmp_path / "grande"
    root.mkdir()
    for n in range(30):
        body = "\n\n".join(f"def funcion_publica_{n}_{k}():\n    pass\n\ndef _privada_{n}_{k}():\n    pass" for k in range(8))
        (root / f"modulo_{n:02d}.py").write_text(body, encoding="utf-8")
    index = CodeIndex(Workspace(root))
    index.refresh()
    outlines = build_outlines(index)

    text = format_map(outlines, max_chars=1500)

    assert len(text) <= 1500 + 60
    assert "modulo_00.py" in text


# ── Cobertura ────────────────────────────────────────────────────────────────

def test_coverage_requires_every_code_file_but_not_tests_or_empty_ones(outlines):
    assert coverage_units(outlines) == ["main.py", "src/core/parser.py"]


def test_coverage_is_per_folder_in_big_projects(tmp_path):
    root = tmp_path / "enorme"
    for folder in ("a", "b", "c"):
        (root / folder).mkdir(parents=True)
        for n in range(10):
            (root / folder / f"m{n}.py").write_text("def f():\n    pass\n", encoding="utf-8")
    index = CodeIndex(Workspace(root))
    index.refresh()

    assert coverage_units(build_outlines(index)) == ["a", "b", "c"]


def test_missing_units_matches_by_path_or_file_name_ignoring_case_and_accents(outlines):
    units = coverage_units(outlines)

    assert missing_units("`main.py` arranca. PARSER.PY lee.", units) == []
    assert missing_units("Solo hablo de main.py", units) == ["src/core/parser.py"]
    assert missing_units("src\\core\\parser.py y main.py", units) == []


def test_footer_says_what_was_read_and_what_is_only_deduced(outlines):
    footer = coverage_footer(outlines, {"main.py"})

    assert "2 ficheros con codigo" in footer
    assert "Leidos a fondo: main.py." in footer
    assert "NO abiertos" in footer and "src/core/parser.py" in footer and "deduccion" in footer


def test_footer_has_no_unread_section_when_everything_was_opened(outlines):
    footer = coverage_footer(outlines, {"main.py", "src/core/parser.py"})

    assert "Leidos a fondo: main.py, src/core/parser.py." in footer and "NO abiertos" not in footer


def test_footer_separates_skimmed_files_from_deep_reads_and_deductions(outlines):
    footer = coverage_footer(outlines, {"main.py"}, summarised={"main.py", "src/core/parser.py"})

    assert "Resumidos a partir de su esquema" in footer and "sin leer el resto: src/core/parser.py" in footer
    assert "Leidos a fondo: main.py." in footer
    assert "NO abiertos" not in footer


# ── Notas por modulo ─────────────────────────────────────────────────────────

def test_the_module_input_has_the_outline_and_the_numbered_head_of_the_file(project, outlines):
    parser = next(o for o in outlines if o.path == "src/core/parser.py")

    text = module_input(project, parser, "Proyecto")

    assert text.startswith("Programa: Proyecto")
    assert "parsear:12" in text and "Mensaje:4 (2 metodos)" in text            # esquema
    assert "def parsear():" in text and "     4\tclass Mensaje:" in text        # cabecera con numeros de linea


def test_the_module_input_is_bounded(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "ancho.py").write_text("def f():\n    pass\n" + "\n".join("x = '" + "a" * 300 + "'" for _ in range(100)), encoding="utf-8")
    index = CodeIndex(Workspace(root))
    index.refresh()
    outline = build_outlines(index)

    assert outline and len(module_input(Workspace(root), outline[0], "p")) == 4_500


def test_notes_are_cleaned_and_bounded():
    assert clean_note("<think>mmm</think>\n- Lee el fichero.\n\nY lo parsea.") == "Lee el fichero. Y lo parsea."
    assert len(clean_note("palabra " * 200)) <= 425
    assert clean_note(None) == "" and clean_note("   ") == ""


def test_the_notes_block_lists_every_module_and_marks_the_unsummarised(outlines):
    text = format_notes(outlines, {"main.py": "Arranca."})

    assert "- main.py (9 lin.): Arranca." in text
    assert "- src/core/parser.py" in text and "sin resumir" in text
    assert "test_parser" not in text


# ── Sintesis ─────────────────────────────────────────────────────────────────

def test_complete_answer_adds_only_the_modules_the_answer_does_not_name(outlines):
    from desktop.code_agent.tour import complete_answer

    units = coverage_units(outlines)
    notes = {"main.py": "Arranca.", "src/core/parser.py": "Parsea."}

    assert complete_answer("`main.py` y `src/core/parser.py`", outlines, notes, units) == "`main.py` y `src/core/parser.py`"
    out = complete_answer("Solo main.py", outlines, notes, units)
    assert "no menciona" in out and "- `src/core/parser.py` (17 lin.): Parsea." in out and "- `main.py`" not in out.split("no menciona")[1]


def test_complete_answer_marks_modules_that_have_no_note(outlines):
    from desktop.code_agent.tour import complete_answer

    out = complete_answer("nada", outlines, {}, coverage_units(outlines))

    assert out.count("sin resumir") == 2


def test_clean_synthesis_drops_reasoning_blocks():
    from desktop.code_agent.tour import clean_synthesis

    assert clean_synthesis("<think>x</think>\n\nHola") == "Hola" and clean_synthesis(None) == ""
