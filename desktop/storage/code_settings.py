"""
desktop/storage/code_settings.py
-----------------------------------
Ajustes del "modo codigo" de PEPO: interruptor general y lista de carpetas de
trabajo AUTORIZADAS. El agente solo trabaja en carpetas de esta lista — la UI
propone una, pero se valida aqui, nunca se confia en la ruta que llega del
cliente (docs/PLAN_PEPO_MODO_CODIGO.md, D4).

Fichero: <config_dir>/code_settings.json (mismo patron que sales_config.json).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from desktop.code_agent.workspace import WorkspaceError, validate_workspace_root
from desktop.storage.atomic_io import atomic_write_text


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


class CodeSettingsStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    # ── Lectura ──────────────────────────────────────────────────────────────

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        workspaces = [str(item) for item in data.get("workspaces", []) if isinstance(item, str)]
        return {"enabled": bool(data.get("enabled", True)), "workspaces": workspaces}

    @property
    def enabled(self) -> bool:
        return self.load()["enabled"]

    def workspaces(self) -> list[str]:
        return self.load()["workspaces"]

    def is_allowed(self, path: str | Path) -> bool:
        """True si `path` es EXACTAMENTE una carpeta autorizada (o esta dentro de una)."""
        try:
            candidate = Path(str(path)).resolve(strict=False)
        except (OSError, RuntimeError):
            return False
        candidate_key = _key(candidate)
        for allowed in self.workspaces():
            allowed_key = _key(Path(allowed).resolve(strict=False))
            if candidate_key == allowed_key or candidate_key.startswith(allowed_key + os.sep):
                return True
        return False

    # ── Escritura ────────────────────────────────────────────────────────────

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        data = self.load()
        data["enabled"] = bool(enabled)
        self._save(data)
        return data

    def add_workspace(self, raw: str) -> dict[str, Any]:
        """Autoriza una carpeta. Lanza WorkspaceError si no es valida o es demasiado amplia."""
        resolved = validate_workspace_root(raw)
        data = self.load()
        if _key(resolved) not in {_key(Path(item).resolve(strict=False)) for item in data["workspaces"]}:
            data["workspaces"].append(str(resolved))
            self._save(data)
        return data

    def remove_workspace(self, raw: str) -> dict[str, Any]:
        data = self.load()
        target = _key(Path(raw).resolve(strict=False))
        data["workspaces"] = [item for item in data["workspaces"] if _key(Path(item).resolve(strict=False)) != target]
        self._save(data)
        return data


__all__ = ["CodeSettingsStore", "WorkspaceError"]
