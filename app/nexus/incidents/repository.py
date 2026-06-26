"""Incident repositories for Nexus."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from nexus.domain.entities.incident import Incident


class MemoryIncidentRepository:
    """In-memory incident repository for local runtime and tests."""

    def __init__(self) -> None:
        self._incidents: dict[str, dict[str, Any]] = {}

    async def upsert(self, incident: Incident) -> dict[str, Any]:
        payload = asdict(incident)
        payload.setdefault("status", "open")
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._incidents[incident.incident_id] = payload
        return payload

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        incidents = list(self._incidents.values())
        incidents.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return incidents[:limit]

    async def get(self, incident_id: str) -> dict[str, Any] | None:
        return self._incidents.get(incident_id)

    async def update(
        self,
        incident_id: str,
        *,
        status: str | None = None,
        owner: str | None = None,
        resolution_note: str | None = None,
        next_action: str | None = None,
    ) -> dict[str, Any] | None:
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None
        if status is not None:
            incident["status"] = status
        if owner is not None:
            incident["owner"] = owner
        if resolution_note is not None:
            incident["resolution_note"] = resolution_note
        if next_action is not None:
            incident["next_action"] = next_action
        incident["updated_at"] = datetime.now(timezone.utc).isoformat()
        return incident


class MongoIncidentRepository:
    """Mongo-backed incident repository."""

    def __init__(self, collection: Any | None) -> None:
        self._col = collection

    async def upsert(self, incident: Incident) -> dict[str, Any]:
        payload = asdict(incident)
        payload.setdefault("status", "open")
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self._col is None:
            return payload
        await asyncio.to_thread(
            self._col.update_one,
            {"incident_id": incident.incident_id},
            {"$set": payload},
            upsert=True,
        )
        return payload

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._col is None:
            return []
        docs = await asyncio.to_thread(
            lambda: list(self._col.find({}).sort("updated_at", -1).limit(limit))
        )
        return [self._serialize(doc) for doc in docs]

    async def get(self, incident_id: str) -> dict[str, Any] | None:
        if self._col is None:
            return None
        doc = await asyncio.to_thread(
            self._col.find_one,
            {"incident_id": incident_id},
        )
        if doc is None:
            return None
        return self._serialize(doc)

    async def update(
        self,
        incident_id: str,
        *,
        status: str | None = None,
        owner: str | None = None,
        resolution_note: str | None = None,
        next_action: str | None = None,
    ) -> dict[str, Any] | None:
        if self._col is None:
            return None
        update_payload: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if status is not None:
            update_payload["status"] = status
        if owner is not None:
            update_payload["owner"] = owner
        if resolution_note is not None:
            update_payload["resolution_note"] = resolution_note
        if next_action is not None:
            update_payload["next_action"] = next_action
        await asyncio.to_thread(
            self._col.update_one,
            {"incident_id": incident_id},
            {"$set": update_payload},
        )
        return await self.get(incident_id)

    @staticmethod
    def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
        payload = dict(doc)
        if "_id" in payload and isinstance(payload["_id"], ObjectId):
            payload["_id"] = str(payload["_id"])
        return payload
