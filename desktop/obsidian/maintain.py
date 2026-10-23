"""
desktop/obsidian/maintain.py
-------------------------------
Mantenimiento de las notas que YA existen (fase 2): enlazar, reparar enlaces rotos, dar formato, etiquetar,
mantener el indice y ordenar en carpetas. Todo son PROPUESTAS (`Change`) con vista previa: nada se escribe hasta
que el usuario confirma.

Casi todo es determinista; el LLM solo interviene para sugerir etiquetas a notas que no tienen (tarea pequeña,
con el vocabulario de etiquetas que ya existe en la boveda). Cada operacion es una funcion pura texto -> texto
para poder componerlas nota a nota (un unico cambio por nota) y probarlas por separado.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from .graph import VaultGraph
from .notes import Note, extract_links, mask_code, split_frontmatter
from .vault import Vault
from .writer import Change, ChangeError, normalise_tags, plan_move, plan_replace, preview_diff, read_raw, render_note

INDEX_START = "<!-- pepo:indice:start -->"
INDEX_END = "<!-- pepo:indice:end -->"
INDEX_TITLES = {"indice de notas", "indice", "indice general", "mapa de notas", "moc", "home"}
DEFAULT_INDEX_TITLE = "Indice de notas"
TAG_CAP = 15                        # notas a etiquetar con LLM por peticion
FIX_CUTOFF = 0.86
OPS = ("fix", "link", "format", "tags", "index", "order")

_FENCE = re.compile(r"(^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\2[`~]*[ \t]*$|\Z))", re.DOTALL | re.MULTILINE)


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


# ── Utilidades de texto ──────────────────────────────────────────────────────

def split_note_text(text: str) -> tuple[str, str]:
    """(frontmatter_con_delimitadores_y_salto, cuerpo). Sin frontmatter el primero es ''."""
    block, body_start = split_frontmatter(text)
    if block is None:
        return "", text
    lines = text.split("\n")
    return "\n".join(lines[: body_start - 1]) + "\n", "\n".join(lines[body_start - 1:])


def _outside_code(body: str, transform) -> str:
    """Aplica `transform` solo a los tramos que no son bloques de codigo."""
    out, last = [], 0
    for match in _FENCE.finditer(body):
        out.append(transform(body[last:match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(transform(body[last:]))
    return "".join(out)


# ── Formato ──────────────────────────────────────────────────────────────────

def format_text(text: str, created: date) -> str:
    """Formato minimo y SEGURO, idempotente: frontmatter con `created` si falta, sin mas de una linea en blanco
    seguida (fuera del codigo) y un unico salto de linea final. No toca encabezados (un `#etiqueta` al principio de
    linea es una etiqueta de Obsidian, no un encabezado mal escrito) ni los espacios de final de linea (dos espacios
    son un salto de linea en Markdown). Una nota en blanco se deja como esta."""
    text = text.replace("\r\n", "\n")
    if not text.strip():
        return text
    prefix, body = split_note_text(text)
    lead = len(body) - len(body.lstrip("\n"))
    core = _outside_code(body.lstrip("\n"), lambda segment: re.sub(r"\n{3,}", "\n\n", segment)).rstrip("\n")
    if prefix:
        if not re.search(r"(?m)^created\s*:", prefix):
            prefix = prefix.replace("---\n", f"---\ncreated: {created.isoformat()}\n", 1)
        # Se respeta la separacion que ya habia tras el frontmatter (0 o 1 linea en blanco): cambiarla solo
        # para uniformar modificaria notas sin necesidad.
        separator = "\n" * min(lead, 1)
    else:
        prefix, separator = f"---\ncreated: {created.isoformat()}\n---\n", "\n"
    return prefix + separator + core + "\n" if core else prefix


# ── Enlaces rotos ────────────────────────────────────────────────────────────

def _closest_title(target: str, graph: VaultGraph) -> str | None:
    """El titulo de nota (o alias) que casi seguro quiso decir el usuario, o None si no hay uno claro."""
    names: dict[str, str] = {}
    for note in graph.notes.values():
        for name in [note.title, *note.aliases]:
            names.setdefault(_plain(name), note.title)
    wanted = _plain(PurePosixPath(target).name)
    ranked = sorted(((difflib.SequenceMatcher(None, wanted, key).ratio(), key) for key in names), reverse=True)
    if not ranked or ranked[0][0] < FIX_CUTOFF:
        return None
    if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] - 0.04 and names[ranked[1][1]] != names[ranked[0][1]]:
        return None                                   # dos candidatas casi iguales: no se elige por el usuario
    return names[ranked[0][1]]


def fix_broken_links(text: str, graph: VaultGraph, source: str) -> tuple[str, list[tuple[str, str]]]:
    """Repara los `[[enlaces]]` rotos que son claramente un error de escritura (mayusculas, acentos, una letra).
    Se conserva lo que el usuario leia como alias. Devuelve (texto, [(antes, despues)])."""
    fixes: list[tuple[str, str]] = []
    for link in extract_links(mask_code(text)):
        if link.kind != "wiki" or link.embed or not link.target:
            continue
        if graph.resolve(link, source).status != "broken":
            continue
        title = _closest_title(link.target, graph)
        if title is None:
            continue
        new = f"[[{title}" + (f"#{link.anchor}" if link.anchor else "") + f"|{link.alias or link.target}]]"
        if new == link.raw:
            continue
        text = text.replace(link.raw, new, 1)
        fixes.append((link.raw, new))
    return text, fixes


# ── Enlazar menciones ────────────────────────────────────────────────────────

def link_text(text: str, graph: VaultGraph, path: str) -> tuple[str, list[str]]:
    """Enlaza la primera mencion de cada nota existente que esta nota nombra sin enlazar (ver VaultGraph.link_mentions).
    Solo el cuerpo: el frontmatter no se toca."""
    prefix, body = split_note_text(text)
    # Lo que ya enlaza el texto ACTUAL (que puede diferir del grafo si un paso anterior reparo enlaces).
    already = {
        resolution.path for link in extract_links(mask_code(text))
        if (resolution := graph.resolve(link, path)).path
    }
    new_body, linked = graph.link_mentions(body, exclude={path} | already)
    return prefix + new_body, linked


# ── Etiquetas ────────────────────────────────────────────────────────────────

def set_tags(text: str, tags: list[str]) -> str:
    """Pone `tags: [a, b]` en el frontmatter (lo crea si no existe) editando el TEXTO, sin tocar el resto."""
    line = "tags: [" + ", ".join(tags) + "]"
    block, body_start = split_frontmatter(text)
    if block is None:
        return f"---\n{line}\n---\n\n" + text.lstrip("\n")
    lines = text.split("\n")
    closing = body_start - 2
    for i in range(1, closing):
        if re.match(r"^tags\s*:", lines[i]):
            j = i + 1
            while j < closing and re.match(r"^\s+-\s", lines[j]):
                j += 1
            lines[i:j] = [line]
            return "\n".join(lines)
    lines.insert(closing, line)
    return "\n".join(lines)


# ── Indice ───────────────────────────────────────────────────────────────────

def describe(note: Note) -> str:
    """Una linea que explica la nota: su primer parrafo util, sin Markdown."""
    for raw in mask_code(note.body).split("\n"):
        line = raw.strip()
        if not line or line.startswith(("#", ">", "|", "![[", "---")):
            continue
        line = re.sub(r"\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]", lambda m: m.group(2) or m.group(1), line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"[*_`~]|^[-+*]\s+", "", line).strip()
        if line:
            return line[:90].rstrip() + ("…" if len(line) > 90 else "")
    return "(vacía)"


def find_index_note(graph: VaultGraph) -> str | None:
    for path, note in sorted(graph.notes.items(), key=lambda item: (item[0].count("/"), item[0])):
        if _plain(note.title) in INDEX_TITLES:
            return path
    return None


def render_index_block(graph: VaultGraph, index_path: str | None, moved: dict[str, str] | None = None) -> str:
    """`moved` (ruta_actual -> ruta_nueva) agrupa las notas por la carpeta en la que QUEDARAN tras el plan."""
    moved = moved or {}
    groups: dict[str, list[str]] = {}
    for path in sorted(graph.notes):
        if path == index_path:
            continue
        final = moved.get(path, path)
        groups.setdefault(final.rsplit("/", 1)[0] if "/" in final else "", []).append(path)
    lines = [INDEX_START, "## Notas por carpeta (generado por PEPO; no edites entre las marcas)"]
    for folder in sorted(groups, key=lambda f: (f == "", f.lower())):
        lines.append(f"\n### {folder or 'Sin carpeta'}")
        for path in sorted(groups[folder], key=lambda p: graph.notes[p].title.lower()):
            note = graph.notes[path]
            lines.append(f"- [[{note.title}]] — {describe(note)}")
    lines.append(INDEX_END)
    return "\n".join(lines)


def plan_index(vault: Vault, graph: VaultGraph, today: date, moved: dict[str, str] | None = None) -> Change | None:
    """Mantiene la zona gestionada de `Indice de notas.md` (entre marcas). Si la nota no existe, la crea."""
    index_path = find_index_note(graph)
    block = render_index_block(graph, index_path, moved)
    if index_path is None:
        index_path = f"{DEFAULT_INDEX_TITLE}.md"
        text = render_note(block, ["indice"], today, "mantenida por PEPO")
        return Change("create", index_path, text, "", text)
    old = read_raw(vault, index_path).replace("\r\n", "\n")
    if INDEX_START in old and INDEX_END in old:
        new = re.sub(re.escape(INDEX_START) + r".*?" + re.escape(INDEX_END), lambda _m: block, old, count=1, flags=re.DOTALL)
    else:
        new = old.rstrip("\n") + ("\n\n" if old.strip() else "") + block + "\n"
    return plan_replace(vault, index_path, new)


# ── Ordenar ──────────────────────────────────────────────────────────────────

def plan_order(
    vault: Vault, graph: VaultGraph, skip: set[str], extra_tags: dict[str, list[str]] | None = None,
) -> tuple[list[Change], list[str]]:
    """Mueve las notas sueltas en la raiz a la carpeta existente cuyo nombre coincide con una de sus etiquetas. No
    inventa carpetas, no sobrescribe y no mueve una nota a la que otras apuntan por ruta (`[[Carpeta/Nota]]`)."""
    folders: dict[str, set[str]] = {}
    for path in graph.notes:
        if "/" in path:
            folder = path.rsplit("/", 1)[0]
            folders.setdefault(_plain(folder.split("/")[-1]), set()).add(folder)
    by_path = {
        PurePosixPath(link.target).name.lower()
        for note in graph.notes.values() for link in note.links if "/" in link.target
    }
    changes: list[Change] = []
    skipped: list[str] = []
    for path, note in sorted(graph.notes.items()):
        if "/" in path or path in skip:
            continue
        dest = ""
        for tag in [*note.tags, *(extra_tags or {}).get(path, [])]:       # tambien las etiquetas que este mismo plan va a poner
            candidates = folders.get(_plain(tag.split("/")[-1]))
            if candidates and len(candidates) == 1:
                dest = f"{next(iter(candidates))}/{PurePosixPath(path).name}"
                break
        if not dest:
            continue
        if dest in graph.notes:
            skipped.append(f"`{path}`: ya hay una nota con ese nombre en `{dest.rsplit('/', 1)[0]}`")
        elif note.title.lower() in by_path:
            skipped.append(f"`{path}`: otras notas la enlazan por ruta y se romperian")
        else:
            changes.append(plan_move(vault, path, dest))
    return changes, skipped


# ── Plan completo ────────────────────────────────────────────────────────────

@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.changes


def find_target(message: str, graph: VaultGraph) -> str | None:
    """Ruta de la nota que el usuario nombra en el mensaje (la de titulo mas largo), o None si habla de toda la boveda."""
    text = " " + _plain(message) + " "
    best: tuple[int, str] | None = None
    for path, note in graph.notes.items():
        title = _plain(note.title)
        if len(title) >= 4 and re.search(r"(?<![\w])" + re.escape(title) + r"(?![\w])", text):
            if best is None or len(title) > best[0]:
                best = (len(title), path)
    return best[1] if best else None


def _created_for(note: Note, today: date) -> date:
    try:
        return date.fromtimestamp(note.mtime) if note.mtime else today
    except (OverflowError, OSError, ValueError):
        return today


async def build_plan(
    vault: Vault, graph: VaultGraph, ops: set[str], *, target: str | None = None, composer: Any = None, today: date | None = None,
) -> Plan:
    """Compone las operaciones pedidas en UN cambio por nota (mas el indice y los movimientos)."""
    today = today or date.today()
    plan = Plan()
    index_path = find_index_note(graph)
    scope = [target] if target else sorted(p for p in graph.notes if p != index_path)

    tag_map: dict[str, list[str]] = {}
    if "tags" in ops and composer is not None:
        vocabulary = sorted({t for n in graph.notes.values() for t in n.tags})
        todo = [p for p in scope if not graph.notes[p].tags and not graph.notes[p].is_empty][:TAG_CAP]
        for path in todo:
            note = graph.notes[path]
            tags = await composer.tags(note.title, note.body, vocabulary)
            if tags:
                tag_map[path] = normalise_tags(tags, set(vocabulary), limit=3)
        if len([p for p in scope if not graph.notes[p].tags and not graph.notes[p].is_empty]) > TAG_CAP:
            plan.skipped.append(f"Etiquetas: solo miro {TAG_CAP} notas por petición; repítelo para seguir con el resto")

    counts = {"fix": 0, "link": 0, "format": 0, "tags": 0}
    note_changes = 0
    for path in scope:
        note = graph.notes[path]
        try:
            text = read_raw(vault, path).replace("\r\n", "\n")
        except ChangeError as exc:
            plan.skipped.append(f"`{path}`: {exc}")
            continue
        new = text
        if "fix" in ops:
            new, fixes = fix_broken_links(new, graph, path)
            counts["fix"] += len(fixes)
        if "link" in ops:
            new, linked = link_text(new, graph, path)
            counts["link"] += len(linked)
        if path in tag_map:
            new = set_tags(new, tag_map[path])
            counts["tags"] += 1
        if "format" in ops:
            formatted = format_text(new, _created_for(note, today))
            counts["format"] += 1 if formatted != new else 0
            new = formatted
        change = plan_replace(vault, path, new)
        if change is not None:
            plan.changes.append(change)
            note_changes += 1

    if "fix" in ops and counts["fix"]:
        plan.summary.append(f"Enlaces rotos reparados: {counts['fix']}")
    if "link" in ops and counts["link"]:
        plan.summary.append(f"Menciones convertidas en enlaces: {counts['link']}")
    if counts["tags"]:
        plan.summary.append(f"Notas etiquetadas: {counts['tags']}")
    if counts["format"]:
        plan.summary.append(f"Notas con formato corregido: {counts['format']}")

    moves: list[Change] = []
    if not target and "order" in ops:
        moves, skipped = plan_order(vault, graph, skip={index_path} if index_path else set(), extra_tags=tag_map)
        plan.skipped.extend(skipped)
        if moves:
            plan.summary.append(f"Notas movidas a su carpeta: {len(moves)}")
        # Una nota que se modifica Y se mueve es UN cambio (si no, el segundo paso vería su hash cambiado).
        edits = {c.path: c for c in plan.changes}
        for move in moves:
            edit = edits.get(move.path)
            if edit is not None:
                move.new_text, move.old_hash, move.old_text = edit.new_text, edit.old_hash, edit.old_text
                plan.changes.remove(edit)
        plan.changes.extend(moves)
    if not target and "index" in ops:
        index_change = plan_index(vault, graph, today, moved={m.path: m.dest for m in moves})
        if index_change is not None:
            plan.changes.append(index_change)
            plan.summary.append(f"Índice: {'creo' if index_change.kind == 'create' else 'actualizo'} `{index_change.path}`")
    return plan


def describe_change(change: Change, limit: int = 700) -> str:
    """Una linea o un trozo de diff para la vista previa de un cambio."""
    if change.kind == "move":
        return f"mover `{change.path}` → `{change.dest}`"
    if change.kind == "create":
        return f"crear `{change.path}`"
    diff = preview_diff(change.old_text.replace("\r\n", "\n"), change.new_text.replace("\r\n", "\n"), change.path)
    diff = "\n".join(line for line in diff.splitlines() if not line.startswith(("---", "+++")))
    return diff if len(diff) <= limit else diff[:limit].rsplit("\n", 1)[0] + "\n…"
