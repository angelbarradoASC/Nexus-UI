"""Odoo CRM connector used by the Nexus outreach bridge."""

from __future__ import annotations

from typing import Any

import httpx


class OdooCRMConnector:
    """Small async wrapper around the Odoo web JSON-RPC endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        database: str,
        username: str,
        password: str,
        timeout_seconds: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._database and self._username and self._password)

    async def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": "odoo",
            "configured": self.configured,
            "base_url": self._base_url,
            "database": self._database,
            "username": self._username,
        }
        if not self.configured:
            payload["status"] = "not_configured"
            return payload

        try:
            async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
                response = await client.get(f"{self._base_url}/web/webclient/version_info")
                response.raise_for_status()
                version = response.json()
        except Exception as exc:  # pragma: no cover - network failures vary
            payload["status"] = "down"
            payload["error"] = str(exc)
            return payload

        payload["status"] = "up"
        payload["version"] = version.get("server_version")
        payload["server_serie"] = version.get("server_serie")
        return payload

    async def create_lead(self, lead: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Odoo CRM no esta configurado")

        async with httpx.AsyncClient(timeout=float(self._timeout_seconds), follow_redirects=True) as client:
            auth_response = await client.post(
                f"{self._base_url}/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "db": self._database,
                        "login": self._username,
                        "password": self._password,
                    },
                    "id": 1,
                },
            )
            auth_response.raise_for_status()
            auth_payload = auth_response.json()
            if auth_payload.get("error"):
                raise RuntimeError(auth_payload["error"].get("data", {}).get("message", "No se pudo autenticar en Odoo"))

            create_response = await client.post(
                f"{self._base_url}/web/dataset/call_kw/crm.lead/create",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "model": "crm.lead",
                        "method": "create",
                        "args": [[lead]],
                        "kwargs": {},
                    },
                    "id": 2,
                },
            )
            create_response.raise_for_status()
            create_payload = create_response.json()
            if create_payload.get("error"):
                raise RuntimeError(create_payload["error"].get("data", {}).get("message", "No se pudo crear el lead"))

        return {
            "status": "created",
            "provider": "odoo",
            "lead_id": create_payload.get("result"),
            "base_url": self._base_url,
            "database": self._database,
        }
