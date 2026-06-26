"""Prometheus connector for metric queries and enrichment."""

from __future__ import annotations

from typing import Any

import httpx


class PrometheusConnector:
    """Small async wrapper around the Prometheus query API."""

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def instant_query(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.get(
                f"{self._base_url}/api/v1/query",
                params={"query": query},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", {})
            return data.get("result", [])

    async def healthcheck(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.get(f"{self._base_url}/-/healthy")
            response.raise_for_status()
            return {
                "name": "Prometheus",
                "kind": "collector",
                "status": "up",
                "endpoint": self._base_url,
            }
