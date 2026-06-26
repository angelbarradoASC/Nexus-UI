"""Stores reusable operational context and patterns."""

from __future__ import annotations


class OperationalMemory:
    """In-memory operational notes for v1."""

    def __init__(self) -> None:
        self._notes: dict[str, str] = {}

    def remember(self, key: str, value: str) -> None:
        self._notes[key] = value

    def recall(self, key: str) -> str | None:
        return self._notes.get(key)
