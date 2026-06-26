"""Task entity for orchestration flows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Task:
    """Generic orchestration task."""

    task_id: str
    flow: str
    actor: str
