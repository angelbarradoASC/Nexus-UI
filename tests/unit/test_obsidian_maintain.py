"""tests/unit/test_obsidian_maintain.py

Fase 2 del asistente de Obsidian: mantenimiento de las notas que YA existen (enlazar, reparar enlaces rotos,
dar formato, etiquetar, indice, ordenar) y contraste web de las notas generadas. Todo son propuestas por
lotes con vista previa; aqui se prueba cada operacion pura, el plan compuesto y el flujo de confirmacion.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from desktop.obsidian.assistant import ObsidianAssistant, classify_intent, maintenance_ops, search_queries
from desktop.obsidian.composer import NoteComposer
from desktop.obsidian.graph import VaultGraph
from desktop.obsidian.maintain import (
    INDEX_END,
    INDEX_START,
    build_plan,
    describe,
    find_target,
    fix_broken_links,
    format_text,
    link_text,
    plan_index,
    plan_order,
    set_tags,
)
from desktop.obsidian.vault import Vault
from desktop.obsidian.writer import Change, apply_batch, apply_change, plan_replace
from desktop.storage.obsidian_settings import ObsidianSettingsStore

TODAY = date(2026, 10, 23)


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Boveda"
    (root / ".obsidian").mkdir(parents=True)
    _write(root, "Redes/Cisco ACI.md", "---\ntags: [redes, cisco]\naliases: [Application Centric]\n---\nFabric con topologia spine leaf y APIC.\n")
    _write(root, "Redes/Spine Leaf.md", "---\ntags: [redes]\n---\nTopologia de dos capas.\n")
    _write(root, "Inbox/Idea.md", "Pensando en cisco aci y en la topologia spine leaf.\n\n\n\n\nVer [[Cisco ACl]] y [[Totalmente otra]].\n")
    _write(root, "Suelta.md", "---\ntags: [redes]\n---\nNota suelta sobre switching.\n")
    _write(root, "Sin tags.md", "Los landing zones de Azure ordenan las suscripciones.\n")
    _write(root, "Vacia.md", "")
    _write(root, "Indice de notas.md", "Mi indice personal.\n")
    return root


@pytest.fixture
def vault(vault_root) -> Vault:
    return Vault(vault_root)


@pytest.fixture
def graph(vault) -> VaultGraph:
    return VaultGraph.build(vault)


# ── Formato ──────────────────────────────────────────────────────────────────

def test_format_adds_frontmatter_and_collapses_blank_lines_but_never_touches_code_or_tags():
    text = "#etiqueta suelta\n\nUno\n\n\n\n\nDos  \n```\nx\n\n\n\n\ny\n```\n\n\n\nFin"

    out = format_text(text, TODAY)

    assert out.startswith("---\ncreated: 2026-10-23\n---\n\n#etiqueta suelta\n\nUno\n\nDos  \n```")
    assert "x\n\n\n\n\ny" in out                                       # el codigo no se toca
    assert out.endswith("```\n\nFin\n") and "Dos  \n" in out          # los 2 espacios (salto de linea) se conservan


def test_format_adds_created_to_an_existing_frontmatter_and_is_idempotent():
    once = format_text("---\ntags: [a]\n---\nTexto\n", TODAY)

    assert once == "---\ncreated: 2026-10-23\ntags: [a]\n---\nTexto\n"                # no se inventa una linea en blanco
    assert format_text(once, date(2030, 1, 1)) == once


def test_format_leaves_blank_notes_and_existing_created_alone():
    assert format_text("", TODAY) == "" and format_text("  \n", TODAY) == "  \n"
    already = "---\ncreated: 2020-01-01\n---\n\nHola\n"
    assert format_text(already, TODAY) == already
    assert format_text("---\ncreated: 2020-01-01\n---\n\n\n\nHola", TODAY) == already                 # 3 lineas en blanco -> 1


# ── Enlaces rotos ────────────────────────────────────────────────────────────

def test_a_typo_in_a_link_is_repaired_keeping_what_the_user_read(graph):
    text, fixes = fix_broken_links("Ver [[Cisco ACl#Seccion]] y [[Totalmente otra]].", graph, "Inbox/Idea.md")

    assert text == "Ver [[Cisco ACI#Seccion|Cisco ACl]] y [[Totalmente otra]]."
    assert fixes == [("[[Cisco ACl#Seccion]]", "[[Cisco ACI#Seccion|Cisco ACl]]")]


def test_an_alias_typed_in_other_case_or_accent_resolves_to_its_note(graph):
    text, fixes = fix_broken_links("Ver [[Application Céntric]]", graph, "x.md")

    assert text == "Ver [[Cisco ACI|Application Céntric]]" and len(fixes) == 1


def test_two_equally_close_candidates_are_not_chosen_for_the_user(vault_root):
    _write(vault_root, "Redes/Spine Leaf 1.md", "otra\n")
    _write(vault_root, "Redes/Spine Leaf 2.md", "otra\n")
    graph = VaultGraph.build(Vault(vault_root))

    assert fix_broken_links("[[Spine Leaf 3]]", graph, "x.md")[1] == []


# ── Enlazar ──────────────────────────────────────────────────────────────────

def test_link_text_links_mentions_in_the_body_only_and_not_what_is_already_linked(graph):
    text = "---\ntags: [spine leaf]\n---\n# Cisco ACI\nHablo de cisco aci y de spine leaf. Ya enlazo [[Spine Leaf]]."

    new, linked = link_text(text, graph, "Inbox/Idea.md")

    assert linked == ["Redes/Cisco ACI.md"]
    assert new.startswith("---\ntags: [spine leaf]\n---\n# Cisco ACI\n")                  # frontmatter y encabezado intactos
    assert "Hablo de [[Cisco ACI|cisco aci]] y de spine leaf." in new                      # Spine Leaf ya estaba enlazada


# ── Etiquetas ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("before, after", [
    ("Cuerpo\n", "---\ntags: [a, b]\n---\n\nCuerpo\n"),
    ("---\ncreated: 2026-01-01\n---\nCuerpo\n", "---\ncreated: 2026-01-01\ntags: [a, b]\n---\nCuerpo\n"),
    ("---\ntags:\ncreated: 2026-01-01\n---\nCuerpo\n", "---\ntags: [a, b]\ncreated: 2026-01-01\n---\nCuerpo\n"),
    ("---\ntags:\n  - x\n  - y\ncreated: 2026-01-01\n---\nCuerpo\n", "---\ntags: [a, b]\ncreated: 2026-01-01\n---\nCuerpo\n"),
])
def test_set_tags_edits_the_text_without_disturbing_the_rest(before, after):
    assert set_tags(before, ["a", "b"]) == after


# ── Indice ───────────────────────────────────────────────────────────────────

def test_describe_uses_the_first_useful_line_without_markdown(graph):
    from desktop.obsidian.notes import parse_note

    note = parse_note("x.md", "---\ntags: [a]\n---\n# Titulo\n> [!info] aviso\n\n- **Lee** [[Cisco ACI|ACI]] y [web](http://a.b) `ya`\n")

    assert describe(note) == "Lee ACI y web"         # el codigo en linea no cuenta
    assert describe(parse_note("v.md", "")) == "(vacía)"
    assert describe(parse_note("l.md", "x" * 200)).endswith("…") and len(describe(parse_note("l.md", "x" * 200))) <= 91


def test_the_index_is_created_when_missing_and_stays_idempotent(tmp_path):
    root = tmp_path / "V"
    (root / ".obsidian").mkdir(parents=True)
    _write(root, "A/Uno.md", "Primera nota\n")
    vault = Vault(root)
    change = plan_index(vault, VaultGraph.build(vault), TODAY)

    assert change.kind == "create" and change.path == "Indice de notas.md"
    assert INDEX_START in change.new_text and "### A\n- [[Uno]] — Primera nota" in change.new_text
    apply_change(vault, change)
    assert plan_index(vault, VaultGraph.build(vault), TODAY) is None                  # nada que actualizar


def test_an_existing_index_keeps_the_users_text_and_only_the_managed_block_changes(vault, vault_root):
    graph = VaultGraph.build(vault)
    first = plan_index(vault, graph, TODAY)

    assert first.kind == "replace" and first.new_text.startswith("Mi indice personal.\n\n" + INDEX_START)
    apply_change(vault, first)
    _write(vault_root, "Nueva.md", "Una nota nueva\n")
    second = plan_index(vault, VaultGraph.build(vault), TODAY)

    assert second.new_text.startswith("Mi indice personal.\n\n" + INDEX_START) and "[[Nueva]] — Una nota nueva" in second.new_text
    assert second.new_text.count(INDEX_START) == 1 and second.new_text.endswith(INDEX_END + "\n")
    assert "Indice de notas" not in second.new_text.split(INDEX_START)[1]             # no se lista a si mismo


# ── Ordenar ──────────────────────────────────────────────────────────────────

def test_a_loose_note_moves_to_the_existing_folder_named_like_its_tag(vault, graph):
    moves, skipped = plan_order(vault, graph, skip={"Indice de notas.md"})

    assert [(m.path, m.dest) for m in moves] == [("Suelta.md", "Redes/Suelta.md")] and skipped == []


def test_moves_are_skipped_if_the_destination_exists_or_other_notes_link_by_path(vault, vault_root):
    _write(vault_root, "Redes/Suelta.md", "ya existe\n")
    moves, skipped = plan_order(vault, VaultGraph.build(vault), skip=set())
    assert moves == [] and "ya hay una nota con ese nombre" in skipped[0]

    (vault_root / "Redes/Suelta.md").unlink()
    _write(vault_root, "Apunta.md", "Ver [[Carpeta/Suelta]]\n")
    moves, skipped = plan_order(vault, VaultGraph.build(vault), skip=set())
    assert moves == [] and "se romperian" in skipped[0]


def test_ordering_never_invents_folders(vault_root):
    _write(vault_root, "Solo.md", "---\ntags: [carpeta-que-no-existe]\n---\ntexto\n")
    vault = Vault(vault_root)

    assert plan_order(vault, VaultGraph.build(vault), skip=set())[0][0].path == "Suelta.md"      # solo la que casa con una carpeta real
    assert all(m.path != "Solo.md" for m in plan_order(vault, VaultGraph.build(vault), skip=set())[0])


# ── Plan completo ────────────────────────────────────────────────────────────

class _TagComposer:
    def __init__(self, tags=("azure", "gobernanza")):
        self.tags_to_give = list(tags)
        self.calls = 0

    async def tags(self, title, body, vocabulary):
        self.calls += 1
        return self.tags_to_give


@pytest.mark.asyncio
async def test_the_plan_composes_every_operation_into_one_change_per_note(vault, graph):
    plan = await build_plan(vault, graph, {"fix", "link", "format"}, today=TODAY)

    paths = [c.path for c in plan.changes]
    idea = next(c for c in plan.changes if c.path == "Inbox/Idea.md")
    assert paths.count("Inbox/Idea.md") == 1 and "Indice de notas.md" not in paths and "Vacia.md" not in paths
    assert "[[Spine Leaf|spine leaf]]" in idea.new_text                                                      # enlazado
    assert "[[Cisco ACI|Cisco ACl]]" in idea.new_text and "[[Totalmente otra]]" in idea.new_text           # reparado / irreparable
    assert "[[Cisco ACI|cisco aci]]" not in idea.new_text            # el enlace reparado ya cubre a Cisco ACI: no se duplica
    assert idea.new_text.startswith("---\ncreated: ") and "\n\n\n" not in idea.new_text                    # formato
    assert any(line.startswith("Menciones convertidas en enlaces") for line in plan.summary)


@pytest.mark.asyncio
async def test_linking_alone_links_both_mentions_because_nothing_repaired_the_typo(vault, graph):
    plan = await build_plan(vault, graph, {"link"}, target="Inbox/Idea.md", today=TODAY)

    text = plan.changes[0].new_text
    assert "[[Cisco ACI|cisco aci]]" in text and "[[Spine Leaf|spine leaf]]" in text and "[[Cisco ACl]]" in text


@pytest.mark.asyncio
async def test_only_the_requested_operations_run(vault, graph):
    plan = await build_plan(vault, graph, {"format"}, today=TODAY)

    assert plan.summary == ["Notas con formato corregido: 6"] or plan.summary[0].startswith("Notas con formato corregido")
    assert all("[[Cisco ACI|cisco aci]]" not in c.new_text for c in plan.changes)


@pytest.mark.asyncio
async def test_a_named_note_limits_the_plan_to_that_note(vault, graph):
    target = find_target("enlaza la nota Idea por favor", graph)
    plan = await build_plan(vault, graph, {"link", "index", "order"}, target=target, today=TODAY)

    assert target == "Inbox/Idea.md" and [c.path for c in plan.changes] == ["Inbox/Idea.md"]     # sin indice ni movimientos


@pytest.mark.asyncio
async def test_tags_come_from_the_llm_for_untagged_notes_only_and_are_capped(vault_root, vault, graph):
    composer = _TagComposer()

    plan = await build_plan(vault, graph, {"tags"}, composer=composer, today=TODAY)

    tagged = {c.path for c in plan.changes}
    assert tagged == {"Inbox/Idea.md", "Sin tags.md"} and composer.calls == 2          # Vacia/Indice no; las que ya tienen etiquetas, no
    assert "tags: [azure, gobernanza]" in next(c for c in plan.changes if c.path == "Sin tags.md").new_text

    for n in range(20):
        _write(vault_root, f"Extra {n}.md", f"Texto de la nota numero {n}\n")
    big = VaultGraph.build(Vault(vault_root))
    capped = await build_plan(Vault(vault_root), big, {"tags"}, composer=_TagComposer(), today=TODAY)
    assert any("solo miro 15 notas" in item for item in capped.skipped)


@pytest.mark.asyncio
async def test_after_applying_the_plan_there_is_nothing_left_to_do(vault, vault_root):
    ops = {"fix", "link", "format", "index", "order"}
    first = await build_plan(vault, VaultGraph.build(vault), ops, today=TODAY)
    result = apply_batch(vault, first.changes)

    assert result.failed == [] and len(result.applied) == len(first.changes)
    assert (vault_root / "Redes/Suelta.md").exists() and not (vault_root / "Suelta.md").exists()
    second = await build_plan(vault, VaultGraph.build(vault), ops, today=TODAY)
    assert second.empty, [c.path for c in second.changes]


def test_a_batch_continues_after_a_failure_and_reports_it(vault, vault_root):
    good = plan_replace(vault, "Vacia.md", "contenido\n")
    stale = plan_replace(vault, "Sin tags.md", "otro\n")
    (vault_root / "Sin tags.md").write_text("alguien lo cambio\n", encoding="utf-8")

    result = apply_batch(vault, [stale, good])

    assert [a["path"] for a in result.applied] == ["Vacia.md"] and result.failed[0][0] == "Sin tags.md"
    assert "ha cambiado" in result.failed[0][1] and (vault_root / "Sin tags.md").read_text(encoding="utf-8") == "alguien lo cambio\n"


def test_replace_keeps_the_original_line_endings_and_makes_a_backup(vault, vault_root):
    _write(vault_root, "Crlf.md", "uno\r\ndos\r\n")
    change = plan_replace(vault, "Crlf.md", "uno\ndos\ntres\n")

    result = apply_batch(vault, [change])

    assert (vault_root / "Crlf.md").read_bytes() == b"uno\r\ndos\r\ntres\r\n"
    assert (vault_root / result.applied[0]["backup"]).read_bytes() == b"uno\r\ndos\r\n"
    assert plan_replace(vault, "Crlf.md", "uno\ndos\ntres\n") is None                 # sin cambios -> sin propuesta


# ── Peticiones ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, ops", [
    ("enlaza mis notas entre sí", {"link"}),
    ("ordena mi bóveda y dale formato", {"order", "format"}),
    ("arregla mi bóveda", {"fix", "format"}),
    ("arregla los enlaces rotos", {"fix"}),
    ("etiqueta las notas que no tienen", {"tags"}),
    ("actualiza el índice de notas", {"index"}),
    ("mantén mi bóveda ordenada", {"fix", "link", "format", "tags", "index", "order"}),
    ("enlaza mis notas entre sí y ordénalas", {"link", "order"}),
    ("revisa los enlaces rotos de mi bóveda", set()),
    ("repasa mi bóveda", set()),
])
def test_maintenance_requests_are_recognised(message, ops):
    assert maintenance_ops(message) == ops


def test_intent_priority_is_write_then_maintenance_then_audit():
    assert classify_intent("apunta en Obsidian una nota sobre redes") == "write"
    assert classify_intent("enlaza mis notas") == "modify"
    assert classify_intent("repasa mi bóveda") == "audit"
    assert classify_intent("hola") == "unknown"


# ── Flujo del asistente ──────────────────────────────────────────────────────

class _Router:
    """LLM simulado: responde segun la tarea que identifica en el prompt de sistema."""

    def __init__(self, draft=None, webcheck=None, tags=None, contrast=None):
        self.draft, self.webcheck_payload, self.tags_payload = draft, webcheck, tags
        self.contrast_payload = contrast or {"duplicates": [], "contradictions": []}
        self.calls: list[str] = []

    async def call(self, messages, **kwargs):
        system = messages[0]["content"]
        self.calls.append(system[:40])
        if "Redactas UNA nota" in system:
            payload = self.draft
        elif "Contrastas una NOTA con RESULTADOS" in system:
            payload = self.webcheck_payload
        elif "Sugieres etiquetas" in system:
            payload = self.tags_payload
        else:
            payload = self.contrast_payload
        content = json.dumps(payload) if payload is not None else "no es json"
        return SimpleNamespace(error=None, content=content, tool_calls=None)


def _assistant(tmp_path, vault_root, router=None, web_search=None, store=None) -> ObsidianAssistant:
    settings = ObsidianSettingsStore(tmp_path / "s.json", detect=lambda: vault_root)
    return ObsidianAssistant(settings, llm_router=router, store=store, today=lambda: TODAY, web_search=web_search)


@pytest.mark.asyncio
async def test_a_maintenance_request_shows_a_diff_and_writes_nothing_until_confirmed(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root)
    before = (vault_root / "Inbox/Idea.md").read_bytes()

    text = await assistant.handle("mantén mi bóveda ordenada", "c")

    assert "**Propuesta de mantenimiento de tu bóveda**" in text and "Menciones convertidas en enlaces" in text
    assert "````diff" in text and "+" in text and "¿Lo aplico? Responde **sí** o **no**." in text
    assert "mover `Suelta.md` → `Redes/Suelta.md`" in text and "Indice de notas.md" in text
    assert (vault_root / "Inbox/Idea.md").read_bytes() == before and assistant.has_pending("c")


@pytest.mark.asyncio
async def test_confirming_applies_the_whole_batch_with_backups_and_a_second_pass_finds_nothing(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root)
    await assistant.handle("mantén mi bóveda ordenada", "c")

    reply = await assistant.confirm("c")

    assert reply.startswith("Hecho:") and "cambios aplicados" in reply and ".pepo/backups/" in reply
    assert (vault_root / "Redes/Suelta.md").exists() and "[[Spine Leaf|spine leaf]]" in (vault_root / "Inbox/Idea.md").read_text(encoding="utf-8")
    assert "pepo:indice:start" in (vault_root / "Indice de notas.md").read_text(encoding="utf-8")
    assert "no hay nada que cambiar" in await assistant.handle("mantén mi bóveda ordenada", "c")


@pytest.mark.asyncio
async def test_a_request_about_a_single_note_only_touches_that_note(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root)

    text = await assistant.handle("enlaza la nota Idea", "c")
    await assistant.confirm("c")

    assert "**Propuesta de mantenimiento de la nota `Inbox/Idea.md`**" in text
    assert "Spine Leaf|spine leaf" in (vault_root / "Inbox/Idea.md").read_text(encoding="utf-8")
    assert (vault_root / "Suelta.md").exists()                                      # no se movio: solo se pidio la nota Idea


@pytest.mark.asyncio
async def test_tagging_uses_the_llm_and_without_one_it_is_skipped(tmp_path, vault_root):
    with_llm = _assistant(tmp_path, vault_root, _Router(tags={"tags": ["Azure", "gobernanza"]}))
    text = await with_llm.handle("etiqueta las notas que no tienen", "c")
    assert "Notas etiquetadas: 2" in text

    without = _assistant(tmp_path, vault_root, None)
    assert "no hay nada que cambiar" in await without.handle("etiqueta las notas que no tienen", "c2")


@pytest.mark.asyncio
async def test_a_stale_batch_reports_each_failure_and_applies_the_rest(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root)
    await assistant.handle("da formato a mi bóveda", "c")
    (vault_root / "Sin tags.md").write_text("cambiado a mano\n", encoding="utf-8")

    reply = await assistant.confirm("c")

    assert "No he podido aplicar 1" in reply and "`Sin tags.md`" in reply and "ha cambiado" in reply
    assert (vault_root / "Sin tags.md").read_text(encoding="utf-8") == "cambiado a mano\n"


@pytest.mark.asyncio
async def test_an_empty_vault_has_nothing_to_maintain(tmp_path):
    root = tmp_path / "Vacia"
    (root / ".obsidian").mkdir(parents=True)

    assert "no tiene notas todavía" in await _assistant(tmp_path, root).handle("enlaza mis notas", "c")


@pytest.mark.asyncio
async def test_a_pending_batch_survives_a_restart(tmp_path, vault_root):
    class Store:
        def __init__(self):
            self.rows = {}

        def save(self, *, agent_id, context_id, kind, payload):
            self.rows[(agent_id, context_id)] = json.loads(json.dumps(payload))

        def delete(self, *, agent_id, context_id):
            self.rows.pop((agent_id, context_id), None)

        def list_for_agent(self, agent_id):
            return [SimpleNamespace(context_id=c, payload=p) for (a, c), p in self.rows.items() if a == agent_id]

    store = Store()
    await _assistant(tmp_path, vault_root, store=store).handle("mantén mi bóveda ordenada", "c")
    second = _assistant(tmp_path, vault_root, store=store)
    second.load_pending_from_store()

    assert second.has_pending("c") and (await second.list_pending())[0]["summary"].startswith("Mantenimiento de la bóveda")
    assert "cambios aplicados" in await second.confirm("c") and store.rows == {}


# ── Contraste con internet (notas generadas) ─────────────────────────────────

GENERATED = {"title": "Landing zones de Azure", "body": "Una landing zone prepara la suscripcion de Azure.", "tags": ["azure"]}
RESULTS = [
    {"title": "Azure landing zones | Microsoft", "url": "https://learn.microsoft.com/azure/landing-zones", "description": "Base de suscripciones"},
    {"title": "CAF", "url": "https://learn.microsoft.com/caf", "description": "Cloud adoption framework"},
]


@pytest.mark.asyncio
async def test_a_generated_note_is_checked_against_the_web_and_gets_its_sources(tmp_path, vault_root):
    searched = []

    async def web_search(query):
        searched.append(query)
        return RESULTS

    router = _Router(draft=GENERATED, webcheck={"problemas": [], "fuentes": [1, 2, 9]})
    assistant = _assistant(tmp_path, vault_root, router, web_search)

    text = await assistant.handle("apunta en Obsidian una nota sobre las landing zones de Azure", "c")
    await assistant.confirm("c")

    assert searched == ["Landing zones Azure"]                                   # solo el titulo sale a internet
    assert "contrastada con 2 fuente(s) web (revísala)" in text and "Contraste con internet: nada contradicho en 2 fuente(s)" in text
    note = (vault_root / "Landing zones de Azure.md").read_text(encoding="utf-8")
    assert "[!info] Nota generada por PEPO y contrastada automáticamente con 2 fuente(s)" in note
    assert "## Fuentes\n- [Azure landing zones | Microsoft](https://learn.microsoft.com/azure/landing-zones)\n- [CAF](https://learn.microsoft.com/caf)" in note
    assert "[!warning]" not in note


@pytest.mark.asyncio
async def test_claims_the_sources_do_not_support_keep_the_note_unverified(tmp_path, vault_root):
    async def web_search(query):
        return RESULTS

    router = _Router(draft=GENERATED, webcheck={"problemas": [{"afirmacion": "cuesta 500 euros", "motivo": "ninguna fuente lo dice"}], "fuentes": [1]})

    text = await _assistant(tmp_path, vault_root, router, web_search).handle("apunta una nota sobre las landing zones de Azure", "c")

    assert "**Contraste con internet** (datos que las fuentes no respaldan)" in text and "cuesta 500 euros: ninguna fuente lo dice" in text
    assert "Origen: generada por PEPO (sin verificar)" in text and "[!warning]" in text


@pytest.mark.asyncio
async def test_if_the_web_check_cannot_run_the_user_is_told_and_the_note_stays_unverified(tmp_path, vault_root):
    async def broken_search(query):
        raise RuntimeError("sin red")

    text = await _assistant(tmp_path, vault_root, _Router(draft=GENERATED), broken_search).handle("apunta una nota sobre azure", "c")
    assert "No he podido contrastarla con internet" in text and "sin verificar" in text

    async def empty_search(query):
        return []

    text = await _assistant(tmp_path, vault_root, _Router(draft=GENERATED), empty_search).handle("apunta una nota sobre azure", "c2")
    assert "No he podido contrastarla con internet" in text


@pytest.mark.asyncio
async def test_a_dictated_note_never_goes_to_the_web(tmp_path, vault_root):
    async def web_search(query):
        raise AssertionError("no debe buscar nada")

    router = _Router(draft={"title": "Reunion", "body": "- Jueves 10:00", "tags": []})

    text = await _assistant(tmp_path, vault_root, router, web_search).handle(
        "apunta en Obsidian: reunión con Laura el jueves a las 10, revisar presupuesto de red", "c")

    assert "Contraste con internet" not in text and "apuntada por el usuario" in text


@pytest.mark.asyncio
async def test_the_webcheck_ignores_source_numbers_that_do_not_exist_and_unusable_answers():
    composer = NoteComposer(_Router(webcheck={"problemas": [], "fuentes": [0, 3, "x", 2]}))

    check = await composer.webcheck("T", "cuerpo", RESULTS)
    assert check.sources == [("CAF", "https://learn.microsoft.com/caf")]
    assert (await composer.webcheck("T", "cuerpo", [])).available is False
    assert (await NoteComposer(_Router(webcheck=None)).webcheck("T", "c", RESULTS)).available is False


@pytest.mark.asyncio
async def test_a_note_that_is_edited_and_moved_is_one_change_with_the_new_content(vault, vault_root, graph):
    plan = await build_plan(vault, graph, {"format", "order"}, today=TODAY)

    suelta = [c for c in plan.changes if c.path == "Suelta.md"]
    assert len(suelta) == 1 and suelta[0].kind == "move" and suelta[0].dest == "Redes/Suelta.md"
    assert suelta[0].new_text.startswith("---\ncreated: 2026-10-23\ntags: [redes]\n---")
    result = apply_batch(vault, plan.changes)
    assert result.failed == [] and not (vault_root / "Suelta.md").exists()
    assert (vault_root / "Redes/Suelta.md").read_text(encoding="utf-8").startswith("---\ncreated: 2026-10-23")
    assert next((vault_root / ".pepo/backups").rglob("Suelta.md")).read_text(encoding="utf-8").startswith("---\ntags: [redes]")


@pytest.mark.asyncio
async def test_tags_given_by_the_plan_already_count_for_ordering_so_one_pass_converges(vault, vault_root, graph):
    composer = _TagComposer(tags=("redes",))
    plan = await build_plan(vault, graph, {"tags", "order", "index"}, composer=composer, today=TODAY)

    moved = {c.path: c.dest for c in plan.changes if c.kind == "move"}
    assert moved.get("Sin tags.md") == "Redes/Sin tags.md" and "tags: [redes]" in next(c for c in plan.changes if c.path == "Sin tags.md").new_text
    index = next(c for c in plan.changes if c.path == "Indice de notas.md")
    assert "### Redes" in index.new_text and "- [[Sin tags]]" in index.new_text.split("### Redes")[1]      # el indice usa la ruta final

    assert apply_batch(vault, plan.changes).failed == []
    again = await build_plan(vault, VaultGraph.build(vault), {"tags", "order", "index"}, composer=_TagComposer(tags=("redes",)), today=TODAY)
    assert again.empty, [(c.kind, c.path) for c in again.changes]


# ── Limite de uso del proveedor (HTTP 429) e indice fuera de las relacionadas ─

class _RateLimitedRouter:
    """Devuelve 429 las primeras `fails` veces y despues responde con un JSON valido."""

    def __init__(self, fails):
        self.fails, self.calls = fails, 0

    async def call(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.fails:
            return SimpleNamespace(error="http_429 | nivel=L3", content="", tool_calls=None)
        return SimpleNamespace(error=None, content=json.dumps({"tags": ["redes"]}), tool_calls=None)


@pytest.mark.asyncio
async def test_a_rate_limited_call_waits_and_retries_before_giving_up():
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    router = _RateLimitedRouter(fails=2)
    composer = NoteComposer(router, sleep=fake_sleep)

    assert await composer.tags("T", "cuerpo", []) == ["redes"]
    assert waits == [5.0, 12.0] and router.calls == 3 and composer.rate_limited is True

    exhausted = NoteComposer(_RateLimitedRouter(fails=10), sleep=fake_sleep)
    assert await exhausted.tags("T", "cuerpo", []) == [] and exhausted.rate_limited is True


@pytest.mark.asyncio
async def test_the_user_is_told_when_the_provider_limit_was_the_reason(tmp_path, vault_root):
    async def instant(seconds):
        return None

    class Router(_RateLimitedRouter):
        async def call(self, messages, **kwargs):
            if "Redactas UNA nota" in messages[0]["content"]:
                return SimpleNamespace(error=None, content=json.dumps({"title": "Nueva idea sobre ACI", "body": "ACI usa spine leaf.", "tags": []}), tool_calls=None)
            return SimpleNamespace(error="http_429 | nivel=L3", content="", tool_calls=None)

    assistant = _assistant(tmp_path, vault_root, Router(fails=0))
    assistant._composer._sleep = instant

    text = await assistant.handle("apunta una nota sobre cisco aci y spine leaf", "c")

    assert "No he podido contrastarla con tus notas (el proveedor de IA ha limitado el uso" in text


@pytest.mark.asyncio
async def test_the_index_is_never_offered_or_linked_as_a_related_note(tmp_path, vault_root):
    router = _Router(draft={"title": "Notas sobre indices y mapas", "body": "Un indice de notas ayuda a navegar la boveda de notas.", "tags": []})

    text = await _assistant(tmp_path, vault_root, router).handle("apunta una nota sobre el indice de notas", "c")

    assert "[[Indice de notas]]" not in text


def test_search_queries_use_keywords_not_the_whole_title():
    assert search_queries("Landing Zones y su relación con la topología Spine Leaf") == [
        "Landing Zones relación topología Spine Leaf", "Landing Zones relación"]
    assert search_queries("PTP") == ["PTP"] and search_queries("el de la") == ["el de la"]
    assert search_queries("Azure landing zones") == ["Azure landing zones"]


@pytest.mark.asyncio
async def test_the_web_check_retries_with_simpler_queries_until_something_comes_back(tmp_path, vault_root):
    searched = []

    async def web_search(query):
        searched.append(query)
        return RESULTS if len(query.split()) <= 3 else []            # solo la consulta corta devuelve resultados

    router = _Router(draft={"title": "Landing Zones y su relación con la topología Spine Leaf", "body": "Texto.", "tags": []},
                     webcheck={"problemas": [], "fuentes": [1]})

    text = await _assistant(tmp_path, vault_root, router, web_search).handle("apunta una nota sobre landing zones y spine leaf", "c")

    assert searched == ["Landing Zones relación topología Spine Leaf", "Landing Zones relación"]
    assert "Contraste con internet: nada contradicho en 1 fuente(s)" in text


# ── Notas relacionadas: las elige el LLM, no el TF-IDF ───────────────────────

@pytest.mark.asyncio
async def test_only_the_notes_the_llm_calls_related_are_added_as_related_links(tmp_path, vault_root):
    router = _Router(
        draft={"title": "Demo de fabric", "body": "Preparar una demo de la topologia de dos capas, cada leaf conectado a los spine, con cisco aci.", "tags": []},
        contrast={"duplicates": [], "contradictions": [], "relacionadas": ["Spine Leaf", "Inventada", "Vacia"]},
    )
    assistant = _assistant(tmp_path, vault_root, router)

    text = await assistant.handle("apunta una nota sobre la demo de cisco aci con spine leaf y PTP para el cliente", "c")
    await assistant.confirm("c")

    note = (vault_root / "Demo de fabric.md").read_text(encoding="utf-8")
    assert "## Notas relacionadas\n- [[Spine Leaf]]" in note and "Inventada" not in note and "[[Vacia]]" not in note
    assert "Enlaces:" in text


@pytest.mark.asyncio
async def test_without_a_contrast_there_is_no_related_section(tmp_path, vault_root):
    class Failing(_Router):
        async def call(self, messages, **kwargs):
            if "Comparas una NOTA NUEVA" in messages[0]["content"]:
                return SimpleNamespace(error="boom", content="", tool_calls=None)
            return await super().call(messages, **kwargs)

    router = Failing(draft={"title": "Demo de fabric", "body": "Preparar una demo de cisco aci para el cliente.", "tags": []})
    assistant = _assistant(tmp_path, vault_root, router)

    await assistant.handle("apunta una nota sobre la demo de cisco aci para el cliente", "c")
    await assistant.confirm("c")

    assert "Notas relacionadas" not in (vault_root / "Demo de fabric.md").read_text(encoding="utf-8")
