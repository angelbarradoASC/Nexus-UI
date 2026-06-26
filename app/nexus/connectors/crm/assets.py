"""Assets Consultores internal CRM connector."""

from __future__ import annotations

from typing import Any

import httpx


class AssetsCRMConnector:
    """JWT-backed connector for the internal Django CRM in assets-web-api."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._username and self._password)

    async def status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": "assets-web-api",
            "configured": self.configured,
            "base_url": self._base_url,
            "username": self._username,
        }
        if not self.configured:
            payload["status"] = "not_configured"
            return payload

        try:
            user_data = await self.get_user_data()
        except Exception as exc:  # pragma: no cover - network/auth failures vary
            payload["status"] = "down"
            payload["error"] = str(exc)
            return payload

        payload["status"] = "up"
        payload["user"] = user_data
        return payload

    async def get_user_data(self) -> dict[str, Any]:
        return await self._request("GET", "/api/user-data/")

    async def list_tasks(self) -> dict[str, Any]:
        return await self._request("GET", "/api/admin/tasks/")

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/admin/tasks/", json=payload)

    async def update_task(self, task_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", f"/api/admin/tasks/{task_id}/", json=payload)

    async def delete_task(self, task_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/admin/tasks/{task_id}/")

    async def list_users(self) -> dict[str, Any]:
        return await self._request("GET", "/api/admin/users/")

    async def list_companies(self) -> dict[str, Any]:
        return await self._request("GET", "/api/admin/companies/")

    async def list_projects(self) -> dict[str, Any]:
        return await self._request("GET", "/api/admin/projects/")

    async def create_company(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/admin/companies/", json=payload)

    async def update_company_pipeline(self, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/api/pipeline/{company_id}/", json=payload)

    async def add_pipeline_note(self, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/pipeline/{company_id}/notes/", json=payload)

    async def list_pipeline(self, stage: str | None = None) -> dict[str, Any]:
        params = {"stage": stage} if stage else None
        return await self._request("GET", "/api/pipeline/", params=params)

    async def find_company_by_domain(self, domain: str) -> dict[str, Any] | None:
        if not domain:
            return None
        payload = await self.list_pipeline()
        companies = payload.get("companies", [])
        domain = domain.lower()
        return next((company for company in companies if str(company.get("domain", "")).lower() == domain), None)

    async def find_company_by_email(self, email: str) -> dict[str, Any] | None:
        if not email:
            return None
        payload = await self.list_pipeline()
        companies = payload.get("companies", [])
        email = email.lower()
        return next(
            (
                company
                for company in companies
                if str(company.get("contact_email", "")).lower() == email
            ),
            None,
        )

    async def find_company_by_name(self, name: str) -> dict[str, Any] | None:
        if not name:
            return None
        payload = await self.list_pipeline()
        companies = payload.get("companies", [])
        needle = self._normalize_company_name(name)
        return next(
            (
                company
                for company in companies
                if self._normalize_company_name(str(company.get("name", ""))) == needle
            ),
            None,
        )

    async def add_note(self, entity_id: int, note: dict[str, Any]) -> dict[str, Any]:
        return await self.add_pipeline_note(entity_id, note)

    async def update_lead(self, entity_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.update_company_pipeline(entity_id, payload)

    async def create_lead(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.create_company(payload)

    async def add_tag(self, entity_id: int, tag: str) -> dict[str, Any]:
        note_payload = {
            "note_type": "note",
            "content": f"Tag Nexus aplicada: {tag}",
            "is_done": True,
        }
        return await self.add_pipeline_note(entity_id, note_payload)

    def _normalize_company_name(self, value: str) -> str:
        cleaned = value.lower().strip()
        for token in ("ayuntamiento de", "ayuntamiento", "organismo", "mancomunidad", "consorcio", "concejo"):
            cleaned = cleaned.replace(token, " ")
        return " ".join(cleaned.split())

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._authenticate()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def _authenticate(self) -> str:
        if not self.configured:
            raise RuntimeError("Assets CRM no esta configurado")
        async with httpx.AsyncClient(timeout=float(self._timeout_seconds)) as client:
            response = await client.post(
                f"{self._base_url}/api/token/",
                json={"username": self._username, "password": self._password},
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access")
            if not token:
                raise RuntimeError("No se recibio access token del CRM")
            return token
