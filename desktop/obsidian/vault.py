"""
desktop/obsidian/vault.py
----------------------------
La boveda de Obsidian como carpeta de trabajo AUTORIZADA y con sandbox.

Reutiliza el `Workspace` del modo codigo (rutas resueltas dentro de la carpeta, sin `..`, junctions, UNC ni
flujos NTFS; lista negra de ficheros con pinta de credenciales) y añade lo propio de una boveda:

- `.obsidian/` (ajustes y plugins), `.trash/` y `.pepo/` (copias de seguridad de PEPO) no se leen ni se listan.
- Obsidian ignora las carpetas que empiezan por punto; aqui tambien.
- Solo se leen notas `.md` (y se anota que adjuntos existen, para validar `![[foto.png]]`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from desktop.code_agent.workspace import Workspace, WorkspaceError, is_denied_name

from .notes import MAX_NOTE_BYTES, Note, parse_note

VAULT_PRIVATE_DIRS = frozenset({".obsidian", ".trash", ".pepo"})


def obsidian_config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "obsidian" / "obsidian.json"


def detect_open_vault(config_path: Path | None = None) -> Path | None:
    """Boveda que Obsidian tiene abierta (o, si no hay ninguna abierta, la ultima registrada)."""
    try:
        data = json.loads((config_path or obsidian_config_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    vaults = [v for v in (data.get("vaults") or {}).values() if isinstance(v, dict) and v.get("path")]
    vaults.sort(key=lambda v: (bool(v.get("open")), v.get("ts", 0)), reverse=True)
    for entry in vaults:
        candidate = Path(str(entry["path"]))
        if (candidate / ".obsidian").is_dir():
            return candidate
    return None


def validate_vault_root(raw: str) -> Path:
    """Una boveda es una carpeta con `.obsidian` dentro: evita autorizar una carpeta cualquiera por error."""
    root = Workspace(raw).root
    if not (root / ".obsidian").is_dir():
        raise WorkspaceError(f"{root} no parece una boveda de Obsidian (no tiene la carpeta .obsidian). Abrela antes en Obsidian.")
    return root


class Vault(Workspace):
    """Boveda autorizada. Todas las lecturas pasan por `resolve_readable`."""

    def __init__(self, root: str | Path) -> None:
        super().__init__(validate_vault_root(str(root)))
        self.skipped_protected = 0

    def is_denied(self, path: Path) -> bool:
        if super().is_denied(path):
            return True
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            return True
        return any(part.lower() in VAULT_PRIVATE_DIRS for part in parts)

    def iter_vault_files(self) -> Iterator[Path]:
        """Todos los ficheros de la boveda salvo carpetas ocultas/privadas y ficheros con nombre de credenciales."""
        self.skipped_protected = 0
        for current, dirs, files in os.walk(self.root, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (current_path / d).is_symlink())
            for name in sorted(files):
                file_path = current_path / name
                if file_path.is_symlink():
                    continue
                if is_denied_name(name):
                    self.skipped_protected += 1
                    continue
                yield file_path

    def iter_note_paths(self) -> Iterator[Path]:
        for path in self.iter_vault_files():
            if path.suffix.lower() == ".md":
                yield path

    def read_note(self, rel: str) -> Note | None:
        """Lee y analiza una nota. None si no se puede leer o es demasiado grande."""
        path = self.resolve_readable(rel)
        try:
            stat = path.stat()
            if stat.st_size > MAX_NOTE_BYTES:
                return None
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return None
        return parse_note(self.rel(path), text, stat.st_mtime)
