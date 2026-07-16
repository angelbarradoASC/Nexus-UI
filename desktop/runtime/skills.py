"""Desktop-local view of the shared Nexus skill catalogue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


CATALOGUE_DIR = Path(__file__).resolve().parents[2] / "app" / "skills" / "catalogue"


@dataclass(slots=True)
class DesktopSkill:
    """A skill definition loaded from the shared JSON catalogue."""

    skill_id: str
    name: str
    description: str
    triggers: list[str]
    examples: list[str]
    inputs: dict
    execution: dict
    llm: dict

    @property
    def requires_llm(self) -> bool:
        return bool(self.llm.get("required", False))

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "examples": list(self.examples),
            "inputs": self.inputs,
            "execution": self.execution,
            "llm": self.llm,
            "requires_llm": self.requires_llm,
        }


class DesktopSkillCatalogue:
    """Loads the shared skill catalogue without depending on app import side effects."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or CATALOGUE_DIR
        self._skills: dict[str, DesktopSkill] = {}
        self._load()

    def _load(self) -> None:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("*.json")):
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            skill = DesktopSkill(
                skill_id=payload["id"],
                name=payload["name"],
                description=payload["description"],
                triggers=payload.get("triggers", []),
                examples=payload.get("examples", []),
                inputs=payload.get("inputs", {}),
                execution=payload.get("execution", {}),
                llm=payload.get("llm", {}),
            )
            self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> DesktopSkill | None:
        return self._skills.get(skill_id)

    def all(self) -> list[DesktopSkill]:
        return list(self._skills.values())

    def ids(self) -> list[str]:
        return list(self._skills.keys())
