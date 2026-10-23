"""
desktop/obsidian/writer.py
-----------------------------
Escritura SEGURA en la boveda: nombres de fichero, formato de la nota, propuesta de cambio con vista previa y
aplicacion con comprobaciones. El LLM nunca llega aqui: recibe texto ya decidido.

Garantias:
- NUNCA sobrescribe ni borra. Si ya existe una nota con ese titulo, el cambio es AÑADIR al final.
- Antes de modificar una nota existente se copia a `.pepo/backups/<fecha>/` (Obsidian ignora carpetas con punto).
- Un cambio se aplica solo si la nota sigue como cuando se propuso (hash); si cambio entretanto, se aborta.
- Solo `.md` dentro de la boveda y fuera de `.obsidian/`, `.trash/`, `.pepo/` y nombres de credenciales.
- Escritura atomica y en bytes: los saltos de linea de una nota existente se conservan (no se reescribe a CRLF).
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from desktop.code_agent.workspace import WorkspaceError

from .graph import VaultGraph
from .vault import Vault

_INVALID_NAME = re.compile(r'[\\/:*?"<>|#^\[\]]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_TITLE_LEN = 100
MAX_TAGS = 5


class ChangeError(Exception):
    """El cambio no se puede aplicar (la nota cambio, ya existe, ruta no permitida...). Mensaje apto para el usuario."""


def safe_title(raw: str) -> str:
    """Titulo -> nombre de fichero valido en Windows y en Obsidian (sin `\\ / : * ? \" < > | # ^ [ ]`)."""
    title = _INVALID_NAME.sub(" ", raw or "")
    title = re.sub(r"\s+", " ", title).strip(" .")
    title = title[:MAX_TITLE_LEN].rstrip(" .")
    if not title or title.lower().split(".")[0] in _RESERVED:
        return "Nota"
    return title


def safe_folder(raw: str) -> str:
    """Carpeta relativa a la boveda ('' = raiz): cada segmento saneado, sin `..` ni carpetas ocultas."""
    parts = []
    for part in re.split(r"[\\/]+", raw or ""):
        part = part.strip()
        if not part or part in {".", ".."} or part.startswith("."):
            continue
        parts.append(safe_title(part))
    return "/".join(parts)


def normalise_tags(tags: list[str], existing: set[str] | None = None, limit: int = MAX_TAGS) -> list[str]:
    """Etiquetas en minusculas, sin '#', con guiones; si ya existe una equivalente en la boveda se usa esa."""
    known = {t.lower(): t for t in (existing or set())}
    out: list[str] = []
    for tag in tags or []:
        clean = re.sub(r"[^\w\-/áéíóúñü]+", "-", str(tag).strip().lstrip("#").lower(), flags=re.UNICODE).strip("-_/")
        if not clean or clean.isdigit():
            continue
        clean = known.get(clean, clean)
        if clean not in out:
            out.append(clean)
    return out[:limit]


def render_note(body: str, tags: list[str], created: date, origin: str = "", extra_aliases: list[str] | None = None) -> str:
    """Nota completa: frontmatter (fecha, etiquetas, origen) + cuerpo. Acaba en un unico salto de linea."""
    lines = ["---", f"created: {created.isoformat()}"]
    if tags:
        lines.append("tags: [" + ", ".join(tags) + "]")
    if extra_aliases:
        lines.append("aliases: [" + ", ".join(extra_aliases) + "]")
    if origin:
        lines.append(f"origen: {origin}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip("\n") + "\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def preview_diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}", n=2))


@dataclass
class Change:
    kind: str                     # "create" | "append"
    path: str                     # relativa a la boveda
    new_text: str                 # contenido COMPLETO resultante
    old_hash: str = ""            # hash del contenido que se leyo al proponer ("" si es nueva)
    added: str = ""               # solo lo añadido (para la vista previa)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "new_text": self.new_text, "old_hash": self.old_hash, "added": self.added}

    @classmethod
    def from_dict(cls, data: dict) -> Change:
        return cls(
            kind=str(data.get("kind", "")), path=str(data.get("path", "")), new_text=str(data.get("new_text", "")),
            old_hash=str(data.get("old_hash", "")), added=str(data.get("added", "")),
        )


def _target(vault: Vault, rel: str) -> Path:
    if not rel.lower().endswith(".md"):
        raise ChangeError("Solo escribo notas Markdown (.md).")
    try:
        path = vault.resolve(rel)
    except WorkspaceError as exc:
        raise ChangeError(str(exc)) from exc
    if vault.is_denied(path):
        raise ChangeError(f"No puedo escribir en esa ruta (protegida): {rel}")
    return path


def plan_new_note(vault: Vault, graph: VaultGraph, title: str, folder: str, text: str) -> Change:
    """Si ya hay una nota con ese titulo (en cualquier carpeta), no se crea otra con el mismo nombre: se AÑADE
    el cuerpo al final de la existente. Si no, es una nota nueva en `folder`."""
    title = safe_title(title)
    existing = [p for p, n in graph.notes.items() if n.title.lower() == title.lower()]
    if existing:
        return plan_append(vault, sorted(existing, key=lambda p: (p.count("/"), p))[0], text, today=None)
    rel = (f"{safe_folder(folder)}/" if safe_folder(folder) else "") + f"{title}.md"
    path = _target(vault, rel)
    if path.exists():                                  # existe pero la bóveda no la leyó (muy grande, etc.)
        raise ChangeError(f"Ya existe `{rel}` y no puedo leerla para añadir; elige otro título.")
    return Change("create", rel, text, "", text)


def plan_append(vault: Vault, rel: str, body: str, today: date | None = None) -> Change:
    """Añade `body` al final de una nota existente bajo un encabezado con la fecha (conserva sus saltos de linea)."""
    path = _target(vault, rel)
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            old_raw = handle.read()
    except OSError as exc:
        raise ChangeError(f"No puedo leer `{rel}`: {exc}") from exc
    newline = "\r\n" if "\r\n" in old_raw else "\n"
    stamp = (today or date.today()).isoformat()
    addition = f"## Añadido el {stamp}\n\n" + _strip_frontmatter(body).strip("\n") + "\n"
    addition = addition.replace("\n", newline)
    # Una linea en blanco entre lo que habia y el bloque nuevo (si la nota estaba en blanco, solo el bloque).
    base = old_raw.rstrip("\r\n")
    new_text = base + newline * 2 + addition if base.strip() else addition
    return Change("append", rel, new_text, sha(old_raw), addition)


def _strip_frontmatter(text: str) -> str:
    match = re.match(r"^---\n.*?\n---\n+", text, re.DOTALL)
    return text[match.end():] if match else text


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(delete=False, dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    temp = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def apply_change(vault: Vault, change: Change, now: datetime | None = None) -> dict:
    """Aplica un cambio ya confirmado. Devuelve {path, kind, backup}. Lanza ChangeError si algo no cuadra."""
    path = _target(vault, change.path)
    now = now or datetime.now()
    backup_rel: str | None = None
    if change.kind == "create":
        if path.exists():
            raise ChangeError(f"`{change.path}` ya existe (alguien la creo mientras tanto); no la sobrescribo.")
    elif change.kind == "append":
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                current = handle.read()
        except OSError as exc:
            raise ChangeError(f"No puedo leer `{change.path}`: {exc}") from exc
        if sha(current) != change.old_hash:
            raise ChangeError(f"`{change.path}` ha cambiado desde que te hice la propuesta; no la toco. Pídemelo otra vez.")
        backup_rel = f".pepo/backups/{now:%Y%m%d-%H%M%S}/{change.path}"
        backup_path = vault.root / backup_rel
        _write_bytes_atomic(backup_path, path.read_bytes())
    else:
        raise ChangeError(f"Tipo de cambio desconocido: {change.kind}")
    _write_bytes_atomic(path, change.new_text.encode("utf-8"))
    return {"path": change.path, "kind": change.kind, "backup": backup_rel}


def relative_folder(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent
