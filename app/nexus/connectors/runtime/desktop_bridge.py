"""Desktop runtime bridge for local execution and telemetry."""

from __future__ import annotations


class DesktopBridge:
    """Placeholder bridge for desktop-runtime interactions."""

    def capabilities(self) -> list[str]:
        return [
            "local_execution",
            "metrics_ingestion",
            "quick_actions",
        ]
