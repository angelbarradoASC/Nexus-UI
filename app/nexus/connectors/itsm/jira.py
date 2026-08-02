"""Jira connector for incident and task flows."""

from __future__ import annotations

from typing import Any


class JiraConnector:
    """Thin Jira connector for Nexus v1.

    In the first version it returns a simulated ticket when Jira is not configured,
    which keeps the flow demonstrable without pretending a real integration exists.
    """

    def __init__(self, cfg) -> None:
        self._cfg = cfg

    async def create_incident_ticket(
        self,
        title: str,
        severity: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        if getattr(self._cfg, "jira_configured", lambda: False)():
            return {
                "provider": "jira",
                "status": "pending_real_integration",
                "project_key": self._cfg.jira_project_key,
                "title": title,
                "severity": severity,
                "details": details,
            }

        return {
            "provider": "jira",
            "status": "simulated",
            "key": f"{self._cfg.jira_project_key}-SIM",
            "title": title,
            "severity": severity,
        }
