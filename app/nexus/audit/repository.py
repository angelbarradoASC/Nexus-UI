"""Audit repositories for Nexus."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from bson import ObjectId

from nexus.audit.models import AuditEntry


class MemoryAuditRepository:
    """In-memory audit repository for local runtime and tests."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    async def append(self, entry: AuditEntry) -> None:
        self._entries.append(asdict(entry))

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self._entries[-limit:]))


class MongoAuditRepository:
    """Mongo-backed audit repository with memory-like interface."""

    def __init__(self, collection: Any | None) -> None:
        self._col = collection

    async def append(self, entry: AuditEntry) -> None:
        if self._col is None:
            return
        await asyncio.to_thread(self._col.insert_one, asdict(entry))

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._col is None:
            return []
        docs = await asyncio.to_thread(
            lambda: list(self._col.find({}).sort("timestamp", -1).limit(limit))
        )
        return [self._serialize(doc) for doc in docs]

    @staticmethod
    def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
        payload = dict(doc)
        if "_id" in payload and isinstance(payload["_id"], ObjectId):
            payload["_id"] = str(payload["_id"])
        return payload
