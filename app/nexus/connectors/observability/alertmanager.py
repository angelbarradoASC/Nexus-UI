"""Alertmanager connector for alerts and silences."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


class AlertmanagerConnector:
    """Small async wrapper around the Alertmanager API."""

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def fetch_alerts(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.get(f"{self._base_url}/api/v2/alerts")
            response.raise_for_status()
            return response.json()

    async def healthcheck(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            for path in ("/-/healthy", "/-/ready", "/api/v2/alerts"):
                response = await client.get(f"{self._base_url}{path}")
                if response.status_code < 400:
                    return {
                        "name": "Alertmanager",
                        "kind": "alarm-routing",
                        "status": "up",
                        "endpoint": self._base_url,
                    }

            metrics_response = await client.get(f"{self._base_url}/metrics")
            if metrics_response.status_code < 400:
                body = metrics_response.text.lower()
                if "alertmanager_" in body:
                    return {
                        "name": "Alertmanager",
                        "kind": "alarm-routing",
                        "status": "up",
                        "endpoint": self._base_url,
                        "reason": "health-via-metrics",
                    }
                raise RuntimeError(
                    "El puerto responde, pero no parece Alertmanager; expone /metrics de otro proceso."
                )

            metrics_response.raise_for_status()

    async def create_silence(
        self,
        alert_name: str,
        created_by: str,
        duration_seconds: int,
        comment: str,
    ) -> str:
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(seconds=duration_seconds)
        payload = {
            "matchers": [{"name": "alertname", "value": alert_name, "isRegex": False}],
            "startsAt": start_time.isoformat(),
            "endsAt": end_time.isoformat(),
            "createdBy": created_by,
            "comment": comment,
        }
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.post(f"{self._base_url}/api/v2/silences", json=payload)
            response.raise_for_status()
            return response.json().get("silenceID", "")
