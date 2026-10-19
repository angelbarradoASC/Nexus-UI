"""Brave Search client for prospecting enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncio
import httpx

from nexus.prospecting.repository import ProspectingRepository


@dataclass(slots=True)
class BraveSearchSettings:
    api_key: str | None
    enabled: bool = False
    rate_limit_seconds: float = 1.0
    timeout: float = 20.0


class BraveSearchClient:
    """Minimal Brave Search API wrapper with raw result persistence."""

    def __init__(
        self,
        *,
        settings: BraveSearchSettings,
        repository: ProspectingRepository,
        dry_run: bool = False,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._dry_run = dry_run
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled and self._settings.api_key)

    async def search(
        self,
        *,
        run_id: str,
        query: str,
        country: str = "es",
        language: str = "es",
        count: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        if self._dry_run or not self.enabled:
            payload = {
                "provider": "brave",
                "query": query,
                "country": country,
                "language": language,
                "count": count,
                "offset": offset,
                "timestamp": timestamp,
                "results": [],
                "dry_run": True,
            }
            await self._repository.save_raw_search(run_id, "brave", query, payload)
            return payload

        async with self._lock:
            async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": str(self._settings.api_key),
                    },
                    params={
                        "q": query,
                        "country": country,
                        "search_lang": language,
                        "count": count,
                        "offset": offset,
                    },
                )
                response.raise_for_status()
                raw = response.json()
            await asyncio.sleep(max(self._settings.rate_limit_seconds, 0.0))

        results = []
        for item in (raw.get("web") or {}).get("results", []):
            results.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "description": str(item.get("description") or "").strip(),
                    "age": item.get("age"),
                    "language": item.get("language"),
                    "family_friendly": item.get("family_friendly"),
                }
            )

        payload = {
            "provider": "brave",
            "query": query,
            "country": country,
            "language": language,
            "count": count,
            "offset": offset,
            "timestamp": timestamp,
            "results": results,
            "raw": raw,
            "dry_run": False,
        }
        await self._repository.save_raw_search(run_id, "brave", query, payload)
        return payload
