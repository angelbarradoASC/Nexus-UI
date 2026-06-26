"""Worker registry for Nexus operational roles."""

from __future__ import annotations


WORKERS: list[dict[str, str]] = [
    {
        "name": "general-worker",
        "flow": "chat",
        "mode": "interactive",
        "status": "ready",
    },
    {
        "name": "monitoring-worker",
        "flow": "monitoring",
        "mode": "event-driven",
        "status": "ready",
    },
    {
        "name": "incident-worker",
        "flow": "incidents",
        "mode": "event-driven",
        "status": "ready",
    },
]


def list_workers() -> list[dict[str, str]]:
    """Expose worker metadata for health and review surfaces."""
    return list(WORKERS)
