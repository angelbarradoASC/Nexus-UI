"""Alert entity for monitoring flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Alert:
    """Normalized monitoring alert."""

    title: str
    severity: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
