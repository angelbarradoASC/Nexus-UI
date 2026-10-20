"""tests/unit/test_code_index.py

Buscador de codigo del agente (desktop/code_agent/index.py): trocea en funciones, compara por
raices entre español e ingles y puntua por cobertura. Se prueba sobre un mini-proyecto real en
disco; el comportamiento sobre Nexus-UI lo mide tests/unit/test_code_agent_eval_set.py.
"""

from __future__ import annotations

import pytest

from desktop.code_agent.index import (
    FIND_CODE_SCHEMA,
    CodeIndex,
    chunk_file,
    expand_query,
    format_hits,
    stem,
    tokenize,
)
from desktop.code_agent.workspace import Workspace

PY = '''"""Servicio de correo."""

MAX_REINTENTOS = 3  # numero maximo de reintentos al enviar


def enviar_correo(destino, asunto):
    """Envia un correo y reintenta si falla."""
    for intento in range(MAX_REINTENTOS):
        if _smtp_send(destino, asunto):
            return True
    return False


def _smtp_send(destino, asunto):
    # Abre la conexion SMTP y manda el mensaje
    return True


class VigilanteBuzon:
    """Vigila la bandeja de entrada."""

    def comprobar_nuevos(self):
        # Mira si hay correos nuevos sin leer
        return []
'''

JS = '''function pickFolder(start) {
  // Abre el selector de carpetas
  return window.pywebview.api.pick_folder(start);
}

const loadSettings = async () => {
  return fetch('/api/settings');
};
'''


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proyecto"
    (root / "src").mkdir(parents=True)
    (root / "src" / "correo.py").write_text(PY, encoding="utf-8")
    (root / "src" / "ui.js").write_text(JS, encoding="utf-8")
    (root / "README.md").write_text("# Proyecto\nHerramienta de correo.\n", encoding="utf-8")
    (root / ".env").write_text("SMTP_PASSWORD=hunter2hunter2\n", encoding="utf-8")
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "node_modules" / "dep" / "index.js").write_text("function envio() {}\n", encoding="utf-8")
    (root / "vendor").mkdir()
    (root / "vendor" / "lib.py").write_text("def enviar_correo_vendor():\n    pass\n", encoding="utf-8")
    ws = Workspace(root)
    index = CodeIndex(ws)
    index.refresh()
    return root, ws, index


# ── Tokenizacion y raices ────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b", [
    ("historial", "history"),
    ("minuto", "minute"),
    ("tapan", "tapa"),
    ("carpetas", "carpeta"),
    ("conversacion", "conversation"),
])
def test_stems_match_across_languages_and_conjugations(a, b):
    assert stem(a) == stem(b)


def test_tokenize_splits_identifiers_and_removes_accents_and_fillers():
    assert tokenize("enviarCorreo_nuevo") == [stem("enviar"), stem("correo"), stem("nuevo")]
    assert tokenize("¿Dónde está la función de envío?") == [stem("envio")]    # relleno fuera, sin acentos


def test_expand_query_adds_spanish_to_english_synonyms_and_drops_fillers():
    groups = expand_query("¿Dónde se comprueba la carpeta autorizada?")
    flat = {alt for group in groups for alt in group}

    assert stem("carpeta") in flat and stem("folder") in flat and stem("workspace") in flat
    assert stem("donde") not in flat                                   # relleno


def test_a_short_prefix_does_not_borrow_unrelated_synonyms():
    """'env' (de .env) no debe heredar los sinonimos de 'enviar' (bug real encontrado al medir)."""
    flat = {alt for group in expand_query("el fichero .env") for alt in group}

    assert stem("send") not in flat and stem("post") not in flat


# ── Troceo ───────────────────────────────────────────────────────────────────

def test_python_is_chunked_into_functions_methods_classes_and_constants():
    chunks = {(c.kind, c.name): c for c in chunk_file("src/correo.py", PY)}

    assert ("funcion", "enviar_correo") in chunks and ("funcion", "_smtp_send") in chunks
    assert ("metodo", "VigilanteBuzon.comprobar_nuevos") in chunks
    assert ("clase", "VigilanteBuzon") in chunks
    assert ("constantes", "MAX_REINTENTOS") in chunks
    assert ("modulo", "correo") in chunks
    method = chunks[("metodo", "VigilanteBuzon.comprobar_nuevos")]
    assert PY.splitlines()[method.start - 1].strip().startswith("def comprobar_nuevos")     # linea real


def test_javascript_functions_and_arrow_functions_are_chunked():
    names = {c.name for c in chunk_file("src/ui.js", JS)}

    assert {"pickFolder", "loadSettings"} <= names


def test_a_file_with_a_bom_is_still_parsed_as_python(project):
    root, ws, _ = project
    (root / "src" / "bom.py").write_bytes(b"\xef\xbb\xbf" + b"def con_bom():\n    return 1\n")
    index = CodeIndex(ws)
    index.refresh()

    kinds = {c.name: c.kind for c in index._chunks if c.path == "src/bom.py"}

    assert kinds == {"con_bom": "funcion"}                             # no cae a "texto" por el BOM


def test_syntax_errors_fall_back_to_text_windows():
    chunks = chunk_file("roto.py", "def roto(:\n    pass\n")

    assert chunks and chunks[0].kind == "texto"


# ── Busqueda ─────────────────────────────────────────────────────────────────

def test_spanish_question_finds_the_function_by_name_docstring_and_comments(project):
    _, _, index = project

    hits = index.search("¿Dónde se envía un correo y se reintenta si falla?")

    assert hits[0].chunk.name == "enviar_correo"
    assert hits[0].location == "src/correo.py:6"


def test_comments_in_spanish_are_searchable(project):
    _, _, index = project

    hits = index.search("¿Quién mira si hay correos nuevos sin leer?")

    assert hits[0].chunk.name == "VigilanteBuzon.comprobar_nuevos"


def test_constants_are_found_by_their_explanatory_comment(project):
    _, _, index = project

    hits = index.search("¿Cuál es el máximo de reintentos?")

    assert any(h.chunk.name == "MAX_REINTENTOS" for h in hits[:3])


def test_english_question_and_javascript_work_too(project):
    _, _, index = project

    hits = index.search("where is the folder picker opened?")

    assert hits[0].chunk.name == "pickFolder"


def test_extra_keywords_from_the_model_rescue_a_vocabulary_mismatch(project):
    _, _, index = project
    question = "¿Qué hace de centinela del buzón?"          # 'centinela' no esta en el codigo

    without = index.search(question)
    with_keywords = index.search(question, extra_terms=["watch", "inbox", "new"])

    assert not any(h.chunk.name == "VigilanteBuzon.comprobar_nuevos" for h in without[:1])
    assert with_keywords[0].chunk.name.startswith("VigilanteBuzon")


def test_protected_files_noise_dirs_and_vendor_are_never_indexed(project):
    _, _, index = project
    paths = {c.path for c in index._chunks}

    assert ".env" not in paths
    assert not any(p.startswith(("node_modules/", "vendor/")) for p in paths)
    assert all("hunter2hunter2" not in "\n".join(c.lines) for c in index._chunks)


def test_hits_per_file_are_capped_so_one_file_does_not_flood_the_list(project):
    _, _, index = project

    hits = index.search("correo", k=10, per_file=1)

    assert len({h.chunk.path for h in hits}) == len(hits)


def test_exclude_prefixes_keep_evaluation_questions_out_of_the_index(project):
    root, ws, _ = project
    (root / "tests" / "eval").mkdir(parents=True)
    (root / "tests" / "eval" / "q.json").write_text('{"q": "enviar correo reintentos"}', encoding="utf-8")
    index = CodeIndex(ws, exclude_prefixes=("tests/eval/",))
    index.refresh()

    assert not any(c.path.startswith("tests/eval/") for c in index._chunks)


def test_empty_or_filler_only_questions_return_nothing(project):
    _, _, index = project

    assert index.search("") == [] and index.search("¿dónde está?") == []


# ── Incremental ──────────────────────────────────────────────────────────────

def test_refresh_only_reprocesses_changed_files(project):
    root, _, index = project

    assert index.refresh() == 0                                         # nada cambio
    (root / "src" / "correo.py").write_text(PY + "\n\ndef purgar_cache():\n    return 'purga'\n", encoding="utf-8")
    (root / "src" / "extra.py").write_text("def extra():\n    pass\n", encoding="utf-8")

    assert index.refresh() == 2
    assert index.search("purgar cache")[0].chunk.name == "purgar_cache"


def test_refresh_forgets_deleted_files(project):
    root, _, index = project
    (root / "src" / "ui.js").unlink()

    assert index.refresh() == 1
    assert not any(c.path == "src/ui.js" for c in index._chunks)


# ── Presentacion ─────────────────────────────────────────────────────────────

def test_format_hits_shows_detail_for_the_first_and_one_line_for_the_rest(project):
    _, _, index = project
    question = "¿Dónde se envía un correo?"
    hits = index.search(question, k=6)

    text = format_hits(hits, question, detail=1)

    assert text.startswith("1. src/correo.py:")
    assert "Otros candidatos" in text
    detailed_part = text.split("Otros candidatos")[0]
    compact_part = text.split("Otros candidatos")[1]
    assert "def " in detailed_part or "return" in detailed_part         # lineas de codigo con numeros
    assert "[coincide" not in compact_part


def test_format_hits_redacts_secrets_and_explains_empty_results(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "cfg.py").write_text("def conectar():\n    password = 'hunter2hunter2'\n    return password\n", encoding="utf-8")
    ws = Workspace(root)
    index = CodeIndex(ws)
    index.refresh()

    text = format_hits(index.search("conectar password"), "conectar password")

    assert "hunter2hunter2" not in text
    assert "Sin resultados" in format_hits([], "x")


def test_the_tool_schema_exposes_question_and_optional_keywords():
    properties = FIND_CODE_SCHEMA["function"]["parameters"]
    assert properties["required"] == ["question"] and "keywords" in properties["properties"]
