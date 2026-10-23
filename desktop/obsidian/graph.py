"""
desktop/obsidian/graph.py
----------------------------
El grafo de enlaces de la boveda: que nota enlaza a cual, cuales estan rotos y que menciones podrian ser
enlaces. Todo determinista (sin LLM): es lo que permite a PEPO "repasar" una boveda sin gastar tokens.

Resolucion de enlaces como Obsidian: `[[Nombre]]` busca por nombre de fichero (sin importar carpeta ni
mayusculas), `[[Carpeta/Nombre]]` por ruta, y tambien se aceptan los `aliases` del frontmatter. Si hay
varias notas con el mismo nombre Obsidian elige una (la de la misma carpeta o la de ruta mas corta): aqui se
elige igual y ademas se marca como AMBIGUO, porque el usuario no controla cual se abrira.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .notes import Link, Note, extract_links, mask_code
from .vault import Vault

_DATE_TITLE = re.compile(r"^\d{4}[-_.]\d{1,2}[-_.]\d{1,2}$")
MIN_MENTION_LEN = 4
MAX_MENTION_TITLES = 3000
_ATTACHMENT_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".mp3", ".mp4", ".wav", ".webm", ".ogg", ".mov", ".csv", ".xlsx", ".docx", ".pptx", ".zip", ".json", ".txt", ".canvas"}


@dataclass(slots=True)
class Resolution:
    status: str                               # "ok" | "ambiguous" | "broken" | "self" | "attachment" | "missing_attachment"
    path: str | None = None
    candidates: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Mention:
    source: str
    target: str            # ruta de la nota que se menciona
    title: str             # texto tal como aparece en la nota
    line: int


class VaultGraph:
    def __init__(self, notes: dict[str, Note], attachments: set[str]) -> None:
        self.notes = notes
        self.attachments = attachments                    # nombres de fichero (minusculas) de los adjuntos de la boveda
        self.by_name: dict[str, list[str]] = {}
        self.by_alias: dict[str, list[str]] = {}
        for path, note in notes.items():
            self.by_name.setdefault(note.title.lower(), []).append(path)
            for alias in note.aliases:
                self.by_alias.setdefault(alias.lower(), []).append(path)
        self.resolutions: dict[str, list[tuple[Link, Resolution]]] = {}
        self.incoming: dict[str, list[str]] = {path: [] for path in notes}
        for path, note in notes.items():
            resolved = [(link, self.resolve(link, path)) for link in note.links]
            self.resolutions[path] = resolved
            for link, resolution in resolved:
                if resolution.path and resolution.path != path and resolution.status in {"ok", "ambiguous"}:
                    self.incoming[resolution.path].append(path)

    # ── Construccion ─────────────────────────────────────────────────────────

    @classmethod
    def build(cls, vault: Vault) -> VaultGraph:
        notes: dict[str, Note] = {}
        for path in vault.iter_note_paths():
            note = vault.read_note(vault.rel(path))
            if note is not None:
                notes[note.path] = note
        attachments = {
            p.name.lower() for p in vault.iter_vault_files() if p.suffix.lower() != ".md"
        }
        return cls(notes, attachments)

    # ── Resolucion ───────────────────────────────────────────────────────────

    def resolve(self, link: Link, source: str) -> Resolution:
        target = link.target
        if not target:
            return Resolution("self", source) if link.anchor else Resolution("broken")
        suffix = PurePosixPath(target).suffix.lower()
        if suffix and suffix in _ATTACHMENT_EXT:
            name = PurePosixPath(target).name.lower()
            return Resolution("attachment") if name in self.attachments else Resolution("missing_attachment")

        key = target.lower()
        if "/" in key:
            wanted = key.strip("/")
            candidates = [p for p in self.notes if p[:-3].lower().endswith(wanted) and (p[:-3].lower() == wanted or p[:-3].lower().endswith("/" + wanted))]
        else:
            candidates = list(self.by_name.get(key, []))
            if not candidates:
                candidates = list(self.by_alias.get(key, []))
        if not candidates:
            return Resolution("broken")
        if len(candidates) == 1:
            return Resolution("ok", candidates[0])
        folder = str(PurePosixPath(source).parent)
        same_folder = [p for p in candidates if str(PurePosixPath(p).parent) == folder]
        chosen = same_folder[0] if same_folder else min(candidates, key=lambda p: (p.count("/"), p))
        return Resolution("ambiguous", chosen, sorted(candidates))

    # ── Consultas ────────────────────────────────────────────────────────────

    def links_to(self, path: str) -> list[str]:
        return sorted(set(self.incoming.get(path, [])))

    def outgoing_notes(self, path: str) -> list[str]:
        return sorted({r.path for _, r in self.resolutions.get(path, []) if r.path and r.path != path and r.status in {"ok", "ambiguous"}})

    def mention_index(self) -> tuple[dict[str, str], re.Pattern[str] | None, set[str]]:
        """(nombre_en_minusculas -> nota, regex que los localiza, nombres AMBIGUOS). Un nombre es ambiguo si lo
        llevan varias notas (titulo o alias): se localiza, pero no se debe enlazar solo."""
        cached = getattr(self, "_mention_cache", None)
        if cached is not None:
            return cached
        names: dict[str, str] = {}
        ambiguous: set[str] = set()
        for path, note in self.notes.items():
            for name in [note.title, *note.aliases]:
                clean = name.strip()
                if len(clean) < MIN_MENTION_LEN or _DATE_TITLE.match(clean):
                    continue
                key = clean.lower()
                if key in names and names[key] != path:
                    ambiguous.add(key)
                names.setdefault(key, path)
        if len(names) > MAX_MENTION_TITLES:
            names = {n: p for n, p in names.items() if len(n) >= 7}
        pattern = None
        if names:
            pattern = re.compile(
                r"(?<![\w])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w])",
                re.IGNORECASE | re.UNICODE,
            )
        self._mention_cache = (names, pattern, ambiguous)
        return self._mention_cache

    def link_mentions(self, text: str, exclude: set[str] | None = None) -> tuple[str, list[str]]:
        """Enlaza en un texto NUEVO la primera mencion de cada nota existente (por titulo o alias): `[[Titulo]]` o
        `[[Titulo|como aparece]]`. No toca codigo, enlaces ni URLs, ni nombres ambiguos. Devuelve (texto, rutas
        enlazadas). Es el codigo, no el LLM, quien enlaza: asi nunca aparece un enlace a una nota que no existe."""
        names, pattern, ambiguous = self.mention_index()
        if pattern is None:
            return text, []
        exclude = exclude or set()
        masked = mask_code(text)
        for link in extract_links(masked):
            masked = masked.replace(link.raw, re.sub(r"[^\n]", " ", link.raw))
        masked = re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), masked)
        replacements: list[tuple[int, int, str]] = []
        done: set[str] = set()
        for match in pattern.finditer(masked):
            key = match.group(1).lower()
            target = names[key]
            if key in ambiguous or target in exclude or target in done:
                continue
            done.add(target)
            shown = text[match.start():match.end()]
            title = self.notes[target].title
            replacements.append((match.start(), match.end(), f"[[{title}]]" if shown == title else f"[[{title}|{shown}]]"))
        for start, end, new in reversed(replacements):
            text = text[:start] + new + text[end:]
        return text, sorted(done)

    def sanitize_links(self, text: str, source: str = "") -> tuple[str, list[str]]:
        """Quita los `[[enlaces]]` de un texto nuevo que no apuntan a ninguna nota (los deja como texto plano, con su
        alias si lo tenian). Devuelve (texto, destinos eliminados). Red de seguridad por si el LLM escribe enlaces."""
        masked = mask_code(text)
        removed: list[str] = []
        for link in extract_links(masked):
            if link.kind != "wiki" or link.embed:
                continue
            if self.resolve(link, source).status == "broken":
                removed.append(link.target)
                text = text.replace(link.raw, link.alias or link.target or link.anchor, 1)
        return text, removed

    def unlinked_mentions(self) -> list[Mention]:
        """Sitios donde una nota nombra el titulo (o alias) de OTRA sin enlazarla. Se omiten titulos cortos o que
        son fechas, y las notas que ya enlazan a ese destino en cualquier otro punto (menos ruido)."""
        names, pattern, _ = self.mention_index()
        if pattern is None:
            return []
        found: list[Mention] = []
        for path, note in self.notes.items():
            linked = set(self.outgoing_notes(path))
            masked = self._mask_for_mentions(note)
            seen: set[str] = set()
            for match in pattern.finditer(masked):
                target = names[match.group(1).lower()]
                if target == path or target in linked or target in seen:
                    continue
                seen.add(target)
                line = masked.count("\n", 0, match.start()) + 1
                found.append(Mention(path, target, match.group(1), line))
        return found

    @staticmethod
    def _mask_for_mentions(note: Note) -> str:
        """Texto de la nota sin frontmatter, codigo, enlaces existentes ni URLs; mismas longitudes y lineas."""
        masked = mask_code(note.text)
        lines = masked.split("\n")
        for index in range(note.body_start_line - 1):
            lines[index] = re.sub(r"[^\n]", " ", lines[index])
        masked = "\n".join(lines)
        for link in extract_links(masked):
            masked = masked.replace(link.raw, re.sub(r"[^\n]", " ", link.raw))
        return re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), masked)
