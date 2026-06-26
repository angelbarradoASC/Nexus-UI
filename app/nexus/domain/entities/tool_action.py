"""Tool action entity for execution flows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ToolAction:
    """Approved tool action ready for execution."""

    name: str
    target: str
    risk: str
