"""
desktop/runtime/agent_settings.py
-------------------------------------
Overrides persistidos para los permisos/activacion de cada skill de PEPO.
Mismo patron que PromptManager con overrides.json: los defaults viven
hardcodeados en DesktopSkillRouter (_SKILL_PERMISSION/_SKILL_CAPABILITIES),
este fichero solo guarda lo que el usuario ha cambiado desde el gestor de
agentes — vacio significa "todo por defecto", no rompe nada existente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AgentSettingsStore:
    """CRUD simple sobre data/agents/agent_settings.json."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}", encoding="utf-8")

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, settings: dict[str, dict[str, Any]]) -> None:
        self._path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_override(self, skill_id: str) -> dict[str, Any] | None:
        return self.load().get(skill_id)

    def set_override(
        self,
        skill_id: str,
        *,
        enabled: bool | None = None,
        permission_level: int | None = None,
    ) -> dict[str, Any]:
        settings = self.load()
        current = dict(settings.get(skill_id, {}))
        if enabled is not None:
            current["enabled"] = enabled
        if permission_level is not None:
            current["permission_level"] = permission_level
        settings[skill_id] = current
        self.save(settings)
        return current
