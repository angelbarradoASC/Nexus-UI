"""
desktop/obsidian/notes.py
----------------------------
Analisis de UNA nota de Obsidian: frontmatter, enlaces, etiquetas y encabezados.

Es analisis de texto puro (sin disco ni LLM). Decisiones:

- El frontmatter se lee con un parser minimo (clave: valor, listas en linea y en bloque) y se conserva el
  texto original: quien modifique una nota debe editar el TEXTO, no volcar un dict (se perderian claves
  desconocidas, comentarios y el orden).
- Los enlaces, etiquetas y encabezados NO se buscan dentro de bloques de codigo, codigo en linea ni
  comentarios (`<!-- -->`, `%% %%`): se enmascaran antes, conservando longitudes para que los numeros de
  linea sigan siendo los del fichero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import unquote

_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[`~]*[ \t]*$|\Z)", re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
_COMMENT = re.compile(r"<!--.*?-->|%%.*?%%", re.DOTALL)

_WIKILINK = re.compile(r"(!?)\[\[([^\[\]\n|#]*)(?:#([^\[\]\n|]*))?(?:\|([^\[\]\n]*))?\]\]")
_MD_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]+)\)")
_TAG = re.compile(r"(?<![\w/#&])#([\w][\w\-/]*)", re.UNICODE)
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

MAX_NOTE_BYTES = 2_000_000


@dataclass(slots=True)
class Link:
    target: str            # nombre o ruta SIN extension .md, ni ancla, ni alias
    line: int              # 1-based en el fichero
    raw: str               # texto original del enlace
    anchor: str = ""       # tras '#': encabezado o ^bloque
    alias: str = ""        # tras '|'
    embed: bool = False    # ![[...]]
    kind: str = "wiki"     # "wiki" | "md"


@dataclass(slots=True)
class Note:
    path: str              # relativa a la boveda, con '/'
    title: str             # nombre del fichero sin extension
    text: str
    frontmatter: dict[str, object] = field(default_factory=dict)
    has_frontmatter: bool = False
    body_start_line: int = 1
    links: list[Link] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    headings: list[tuple[int, int, str]] = field(default_factory=list)       # (nivel, linea, texto)
    mtime: float = 0.0

    @property
    def body(self) -> str:
        lines = self.text.split("\n")
        return "\n".join(lines[self.body_start_line - 1:])

    @property
    def is_empty(self) -> bool:
        return not self.body.strip()

    @property
    def aliases(self) -> list[str]:
        return _as_list(self.frontmatter.get("aliases") or self.frontmatter.get("alias"))


# ── Enmascarado ──────────────────────────────────────────────────────────────

def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def mask_code(text: str) -> str:
    """Sustituye por espacios el codigo (en bloque y en linea) y los comentarios, conservando saltos de linea
    y longitud: los indices y los numeros de linea no cambian."""
    text = _FENCE.sub(_blank, text)
    text = _COMMENT.sub(_blank, text)
    return _INLINE_CODE.sub(_blank, text)


# ── Frontmatter ──────────────────────────────────────────────────────────────

def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [part.strip() for part in re.split(r"[,\s]+" if "," not in text else ",", text) if part.strip()]


def split_frontmatter(text: str) -> tuple[str | None, int]:
    """(bloque_de_frontmatter_sin_delimitadores | None, linea_donde_empieza_el_cuerpo)."""
    lines = text.split("\n")
    if not lines or lines[0].strip("﻿ \t\r") != "---":
        return None, 1
    for index in range(1, len(lines)):
        if lines[index].strip("\r \t") in {"---", "..."}:
            return "\n".join(lines[1:index]), index + 2
    return None, 1


def parse_frontmatter(block: str) -> dict[str, object]:
    """YAML minimo: `clave: valor`, `clave: [a, b]` y listas en bloque. Lo que no entiende lo ignora."""
    data: dict[str, object] = {}
    current: str | None = None
    for raw in block.split("\n"):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and current is not None:
            existing = data.get(current)
            data[current] = (existing if isinstance(existing, list) else []) + [_unquote(item.group(1))]
            continue
        pair = re.match(r"^([^\s:#][^:]*?):\s*(.*)$", line)
        if not pair:
            continue
        current = pair.group(1).strip()
        value = pair.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            data[current] = [_unquote(part) for part in value[1:-1].split(",") if part.strip()]
        elif value == "":
            data[current] = []                      # puede ser una lista en bloque que sigue
        else:
            data[current] = _unquote(value)
    return {key: value for key, value in data.items() if value != [] or key in {"tags", "aliases"}}


# ── Analisis ─────────────────────────────────────────────────────────────────

def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _clean_target(raw: str) -> str:
    target = raw.strip().replace("\\", "/")
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def extract_links(masked: str, first_line: int = 1) -> list[Link]:
    """Enlaces de un texto ya enmascarado. `first_line` es la linea del fichero en la que empieza `masked`."""
    links: list[Link] = []
    for match in _WIKILINK.finditer(masked):
        links.append(Link(
            target=_clean_target(match.group(2)), anchor=(match.group(3) or "").strip(), alias=(match.group(4) or "").strip(),
            embed=bool(match.group(1)), line=first_line + _line_of(masked, match.start()) - 1, raw=match.group(0),
        ))
    for match in _MD_LINK.finditer(masked):
        destination = unquote(match.group(3))
        if _SCHEME.match(destination) or destination.startswith(("#", "/")):
            continue
        base, _, anchor = destination.partition("#")
        if not base:
            continue
        links.append(Link(
            target=_clean_target(base), anchor=anchor, alias=match.group(2), embed=bool(match.group(1)),
            line=first_line + _line_of(masked, match.start()) - 1, raw=match.group(0), kind="md",
        ))
    links.sort(key=lambda link: link.line)
    return links


def parse_note(path: str, text: str, mtime: float = 0.0) -> Note:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    block, body_start = split_frontmatter(text)
    frontmatter = parse_frontmatter(block) if block is not None else {}
    note = Note(
        path=path.replace("\\", "/"), title=PurePosixPath(path.replace("\\", "/")).stem, text=text,
        frontmatter=frontmatter, has_frontmatter=block is not None, body_start_line=body_start, mtime=mtime,
    )

    masked_all = mask_code(text)
    lines = masked_all.split("\n")
    masked_body = "\n".join(lines[body_start - 1:])
    note.links = extract_links(masked_body, body_start)
    note.headings = [
        (len(m.group(1)), body_start + _line_of(masked_body, m.start()) - 1, m.group(2).strip())
        for m in _HEADING.finditer(masked_body)
    ]

    tags = [t.lstrip("#") for t in _as_list(frontmatter.get("tags") or frontmatter.get("tag"))]
    for match in _TAG.finditer(_WIKILINK.sub(_blank, _MD_LINK.sub(_blank, masked_body))):
        name = match.group(1)
        if not name.isdigit():
            tags.append(name)
    note.tags = list(dict.fromkeys(tags))
    return note
