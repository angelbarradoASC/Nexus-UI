"""Grafana connector for lightweight health checks."""

from __future__ import annotations

from typing import Any

import httpx


class GrafanaConnector:
    """Small async wrapper around Grafana health endpoints."""

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def healthcheck(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.get(f"{self._base_url}/api/health")
            response.raise_for_status()
            payload = response.json()
            return {
                "name": "Grafana",
                "kind": "visualization",
                "status": "up" if payload.get("database") == "ok" else "degraded",
                "endpoint": self._base_url,
                "reason": payload.get("message", ""),
            }
