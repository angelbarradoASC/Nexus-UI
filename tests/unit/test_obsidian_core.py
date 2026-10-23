"""tests/unit/test_obsidian_core.py

Nucleo del asistente de Obsidian (docs/PLAN_PEPO_OBSIDIAN.md, fase 0): analisis de notas, sandbox de la
boveda, grafo de enlaces y auditoria. Todo determinista y de solo lectura.
"""

from __future__ import annotations

import json

import pytest

from desktop.code_agent.workspace import WorkspaceError
from desktop.obsidian.audit import audit_graph, format_report
from desktop.obsidian.graph import VaultGraph
from desktop.obsidian.notes import mask_code, parse_note
from desktop.obsidian.vault import Vault, detect_open_vault, validate_vault_root


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Boveda"
    (root / ".obsidian").mkdir(parents=True)
    _write(root, ".obsidian/app.json", "{}")
    _write(root, ".pepo/backups/viejo.md", "# copia que PEPO no debe leer")
    _write(root, "Redes/Cisco ACI.md", "---\ntags: [redes, cisco]\naliases:\n  - ACI\n  - Application Centric\ncreated: 2026-10-01\n---\n# Cisco ACI\nFabric basada en spine y leaf.\n")
    _write(root, "Redes/Spine Leaf.md", "---\ntags: redes\n---\nTopologia de dos capas. Ver [[Cisco ACI]].\n")
    _write(root, "Inbox/Idea.md", (
        "Pensando en [[Cisco ACI]] y en [[Cisco ACI#Fundamentos|ACI]].\n"
        "Falta [[No existe]] y la imagen ![[diagrama.png]] pero ![[falta.png]] no esta.\n"
        "La topologia spine leaf deberia enlazarse. #redes #123\n"
        "```\n[[En codigo]]\n```\nY `[[tambien codigo]]` no cuenta. Web: [x](https://ejemplo.com/Cisco%20ACI.md)\n"
        "Enlace md: [capas](Spine%20Leaf.md)\n"
    ))
    _write(root, "Otro/Idea.md", "Otra idea con el mismo nombre.\n")
    _write(root, "Resumen.md", "Mira [[Idea]] para el detalle.\n")
    _write(root, "Vacia.md", "")
    _write(root, "Nota (conflicto).md", "Copia generada por OneDrive.\n")
    _write(root, "Credentials.md", "usuario: admin\npassword: hunter2hunter2\n")
    (root / "diagrama.png").write_bytes(b"\x89PNG")
    return root


@pytest.fixture
def vault(vault_root) -> Vault:
    return Vault(vault_root)


@pytest.fixture
def graph(vault) -> VaultGraph:
    return VaultGraph.build(vault)


# ── Analisis de una nota ─────────────────────────────────────────────────────

def test_frontmatter_is_parsed_in_all_its_list_forms():
    note = parse_note("a.md", "---\ntags: [uno, dos]\naliases:\n  - A\n  - 'B c'\ntitle: \"Hola: mundo\"\n---\ncuerpo")

    assert note.has_frontmatter and note.frontmatter["tags"] == ["uno", "dos"]
    assert note.aliases == ["A", "B c"] and note.frontmatter["title"] == "Hola: mundo"
    assert note.body_start_line == 8 and note.body == "cuerpo"


def test_a_note_without_frontmatter_or_with_unclosed_frontmatter():
    assert not parse_note("a.md", "solo texto").has_frontmatter
    unclosed = parse_note("a.md", "---\ntags: [a]\nsin cerrar")
    assert not unclosed.has_frontmatter and unclosed.body_start_line == 1


def test_wikilinks_keep_target_anchor_alias_embed_and_the_file_line():
    note = parse_note("a.md", "---\ntags: x\n---\nuno [[B]]\n\ndos [[C#Seccion|alias]] y ![[img.png]] y [[Dir/D.md]]")

    simple, aliased, embed, with_path = note.links
    assert (simple.target, simple.line) == ("B", 4)
    assert (aliased.target, aliased.anchor, aliased.alias, aliased.line) == ("C", "Seccion", "alias", 6)
    assert embed.embed and embed.target == "img.png"
    assert with_path.target == "Dir/D"                                  # sin .md


def test_markdown_links_to_notes_count_but_urls_and_anchors_do_not():
    note = parse_note("a.md", "[x](Otra%20nota.md) [web](https://a.com/b.md) [mail](mailto:a@b.c) [h](#seccion) [r](/abs.md)")

    assert [link.target for link in note.links] == ["Otra nota"] and note.links[0].kind == "md"


def test_code_comments_and_inline_code_hide_links_tags_and_headings():
    text = "```\n[[A]] #tag\n# no soy titulo\n```\n`[[B]]` <!-- [[C]] --> %% [[D]] %%\n# Titulo real [[E]] #real\n"
    note = parse_note("a.md", text)

    assert [link.target for link in note.links] == ["E"]
    assert note.tags == ["real"] and [(lvl, txt) for lvl, _, txt in note.headings] == [(1, "Titulo real [[E]] #real")]
    assert mask_code(text).count("\n") == text.count("\n") and len(mask_code(text)) == len(text)


def test_tags_come_from_frontmatter_and_body_without_numbers_or_urls():
    note = parse_note("a.md", "---\ntags: [x, y]\n---\nTexto #z #123 http://a.com/#frag #x")

    assert note.tags == ["x", "y", "z"]


# ── Sandbox de la boveda ─────────────────────────────────────────────────────

def test_a_vault_needs_the_obsidian_folder(tmp_path):
    plain = tmp_path / "carpeta"
    plain.mkdir()

    with pytest.raises(WorkspaceError, match="no parece una boveda"):
        validate_vault_root(str(plain))


def test_private_folders_and_credential_names_are_never_read(vault):
    assert vault.is_denied(vault.root / ".obsidian" / "app.json")
    assert vault.is_denied(vault.root / ".pepo" / "backups" / "viejo.md")
    with pytest.raises(WorkspaceError):
        vault.read_note(".obsidian/app.json")
    with pytest.raises(WorkspaceError):
        vault.read_note("Credentials.md")
    with pytest.raises(WorkspaceError):
        vault.read_note("../fuera.md")
    paths = {vault.rel(p) for p in vault.iter_note_paths()}
    assert "Credentials.md" not in paths and not any(p.startswith((".obsidian", ".pepo")) for p in paths)
    assert vault.skipped_protected == 1


def test_the_open_vault_is_detected_from_obsidian_config(tmp_path, vault_root):
    config = tmp_path / "obsidian.json"
    config.write_text(json.dumps({"vaults": {
        "a": {"path": str(tmp_path / "no_existe"), "ts": 9, "open": True},
        "b": {"path": str(vault_root), "ts": 1},
    }}), encoding="utf-8")

    assert detect_open_vault(config) == vault_root
    assert detect_open_vault(tmp_path / "nada.json") is None


# ── Grafo ────────────────────────────────────────────────────────────────────

def test_links_resolve_by_name_alias_path_and_attachment(graph):
    statuses = {(link.raw, res.status): res.path for link, res in graph.resolutions["Inbox/Idea.md"]}

    assert statuses[("[[Cisco ACI]]", "ok")] == "Redes/Cisco ACI.md"
    assert statuses[("[[Cisco ACI#Fundamentos|ACI]]", "ok")] == "Redes/Cisco ACI.md"
    assert ("[[No existe]]", "broken") in statuses
    assert ("![[diagrama.png]]", "attachment") in statuses and ("![[falta.png]]", "missing_attachment") in statuses
    assert statuses[("[capas](Spine%20Leaf.md)", "ok")] == "Redes/Spine Leaf.md"


def test_an_alias_resolves_to_its_note(vault_root):
    _write(vault_root, "Usa alias.md", "Ver [[ACI]] y [[application centric]].\n")
    graph = VaultGraph.build(Vault(vault_root))

    assert [r.path for _, r in graph.resolutions["Usa alias.md"]] == ["Redes/Cisco ACI.md", "Redes/Cisco ACI.md"]


def test_same_named_notes_make_the_link_ambiguous_and_pick_the_shortest_path(graph):
    (link, resolution), = graph.resolutions["Resumen.md"]

    assert resolution.status == "ambiguous" and set(resolution.candidates) == {"Inbox/Idea.md", "Otro/Idea.md"}
    assert resolution.path == "Inbox/Idea.md"


def test_incoming_and_outgoing_links(graph):
    assert graph.links_to("Redes/Cisco ACI.md") == ["Inbox/Idea.md", "Redes/Spine Leaf.md"]
    assert "Redes/Spine Leaf.md" in graph.outgoing_notes("Inbox/Idea.md")


def test_unlinked_mentions_ignore_code_existing_links_titles_that_are_dates_and_short_names(graph, vault_root):
    mentions = {(m.source, m.target) for m in graph.unlinked_mentions()}

    # "spine leaf" aparece en texto plano en Idea.md y en Cisco ACI.md ("spine y leaf" NO es el titulo)
    assert ("Inbox/Idea.md", "Redes/Spine Leaf.md") not in mentions        # ya la enlaza con [capas](Spine%20Leaf.md)
    _write(vault_root, "Diario.md", "Hoy repase la topologia spine leaf y el 2026-10-01. Tambien Cisco ACI.\n")
    _write(vault_root, "2026-10-01.md", "dia")
    graph2 = VaultGraph.build(Vault(vault_root))
    found = {(m.source, m.target) for m in graph2.unlinked_mentions()}
    assert ("Diario.md", "Redes/Spine Leaf.md") in found and ("Diario.md", "Redes/Cisco ACI.md") in found
    assert not any(target == "2026-10-01.md" for _, target in found)


# ── Auditoria ────────────────────────────────────────────────────────────────

def test_audit_finds_the_known_problems_with_path_and_line(graph, vault):
    report = audit_graph(graph, "Boveda", vault.skipped_protected)

    assert report.notes == 7 and report.skipped_protected == 1
    assert ("Inbox/Idea.md", 2, "[[No existe]]") in report.broken
    assert [m[2] for m in report.missing_attachments] == ["![[falta.png]]"]
    assert report.ambiguous and report.ambiguous[0][0] == "Resumen.md"
    assert report.empty == ["Vacia.md"]
    assert report.duplicate_titles == {"idea": ["Inbox/Idea.md", "Otro/Idea.md"]}
    assert report.conflict_copies == ["Nota (conflicto).md"]
    assert "Otro/Idea.md" in report.orphans and "Redes/Cisco ACI.md" not in report.orphans
    assert "Inbox/Idea.md" in report.no_frontmatter and "Redes/Cisco ACI.md" not in report.no_frontmatter


def test_the_report_is_readable_and_truncates_long_lists(graph, vault):
    text = format_report(audit_graph(graph, "Boveda", vault.skipped_protected), limit=1)

    assert text.startswith("**Repaso de la bóveda «Boveda»**: 7 notas")
    assert "Enlaces rotos" in text and "`Inbox/Idea.md` línea 2: [[No existe]]" in text
    assert "… y " in text                                                    # recortado a 1 por seccion
    assert "1 ficheros con nombre de credenciales no se han leído" in text


def test_an_empty_vault_and_a_clean_vault(tmp_path):
    root = tmp_path / "V"
    (root / ".obsidian").mkdir(parents=True)
    empty = VaultGraph.build(Vault(root))
    assert "No hay ninguna nota" in format_report(audit_graph(empty, "V"))

    _write(root, "A.md", "---\ntags: [x]\n---\nVer [[B]].\n")
    _write(root, "B.md", "---\ntags: [x]\n---\nVuelve a [[A]].\n")
    clean = format_report(audit_graph(VaultGraph.build(Vault(root)), "V"))
    assert "No he encontrado problemas" in clean
