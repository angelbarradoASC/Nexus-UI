"""ServiceNow connector for incident and task flows."""

from __future__ import annotations

from typing import Any


class ServiceNowConnector:
    """Minimal ServiceNow placeholder for the production path."""

    async def create_incident(
        self,
        title: str,
        severity: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": "servicenow",
            "status": "not_configured",
            "title": title,
            "severity": severity,
            "details": details,
        }
