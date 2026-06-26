"""Risk classification rules for actions and incidents."""

from __future__ import annotations


def classify_severity(severity: str) -> str:
    """Normalize severities into a small controlled set."""
    normalized = severity.lower().strip()
    if normalized in {"critical", "high"}:
        return "critical"
    if normalized in {"warning", "medium"}:
        return "warning"
    return "info"
