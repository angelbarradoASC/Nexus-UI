"""
desktop/storage/obsidian_settings.py
---------------------------------------
Ajustes del asistente de Obsidian de PEPO (docs/PLAN_PEPO_OBSIDIAN.md): interruptor y boveda autorizada.

La boveda NUNCA la elige el LLM ni llega del chat: sale de aqui. Si el usuario no ha fijado ninguna, se usa la
que Obsidian tiene abierta (`obsidian.json`). Fichero: <config_dir>/obsidian_settings.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from desktop.obsidian.vault import detect_open_vault, validate_vault_root
from desktop.storage.atomic_io import atomic_write_text


class ObsidianSettingsStore:
    def __init__(self, path: str | Path, *, detect=detect_open_vault) -> None:
        self._path = Path(path)
        self._detect = detect

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        return {"enabled": bool(data.get("enabled", True)), "vault": str(data.get("vault", "") or "").strip()}

    @property
    def enabled(self) -> bool:
        return self.load()["enabled"]

    def effective_vault(self) -> tuple[Path | None, str]:
        """(ruta, origen): `configured` (fijada por el usuario), `detected` (la abierta en Obsidian) o `none`."""
        configured = self.load()["vault"]
        if configured:
            path = Path(configured)
            if (path / ".obsidian").is_dir():
                return path, "configured"
        detected = self._detect()
        if detected is not None:
            return detected, "detected"
        return None, "none"

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        data = self.load()
        data["enabled"] = bool(enabled)
        self._save(data)
        return data

    def set_vault(self, raw: str) -> dict[str, Any]:
        """Fija la boveda. Lanza WorkspaceError si no existe, es demasiado amplia o no tiene `.obsidian`.
        Con una ruta vacia vuelve a usar la boveda abierta en Obsidian."""
        data = self.load()
        data["vault"] = str(validate_vault_root(raw)) if raw and raw.strip() else ""
        self._save(data)
        return data
