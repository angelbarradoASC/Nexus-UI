"""DuckDuckGo search client for prospecting — free, no API key required."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from nexus.prospecting.filters import BLOCKED_EXACT_DOMAINS
from nexus.prospecting.repository import ProspectingRepository

# LinkedIn title pattern: "Nombre Apellido - Cargo en Empresa | LinkedIn"
_LINKEDIN_TITLE_RE = re.compile(
    r"^([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:\s+(?:de\s+)?[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){1,3})"
    r"\s*[-–]\s*"
    r"(.+?)"
    r"\s*(?:\||en\s+[A-Z]|·|$)",
    re.UNICODE,
)
_ROLE_CLEANUP_RE = re.compile(r"\s*(?:\|\s*LinkedIn|en\s+.+|at\s+.+|·.+)$", re.IGNORECASE)


@dataclass(slots=True)
class DdgSearchSettings:
    enabled: bool = True
    rate_limit_seconds: float = 1.5
    timeout: float = 20.0
    max_results_per_query: int = 10


class DdgSearchClient:
    """DuckDuckGo text search — uses duckduckgo-search already in requirements."""

    def __init__(
        self,
        *,
        settings: DdgSearchSettings | None = None,
        repository: ProspectingRepository | None = None,
    ) -> None:
        self._settings = settings or DdgSearchSettings()
        self._repository = repository
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    async def search(
        self,
        *,
        run_id: str,
        query: str,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        count = min(max_results or self._settings.max_results_per_query, 20)
        timestamp = datetime.now(timezone.utc).isoformat()

        if not self.enabled:
            return {"provider": "ddg", "query": query, "results": [], "timestamp": timestamp}

        async with self._lock:
            results = await asyncio.to_thread(self._sync_search, query, count)
            await asyncio.sleep(self._settings.rate_limit_seconds)

        payload = {"provider": "ddg", "query": query, "timestamp": timestamp, "results": results}
        if self._repository and run_id:
            try:
                await self._repository.save_raw_search(run_id, "ddg", query, payload)
            except Exception:
                pass
        return payload

    async def find_linkedin_contact(
        self,
        *,
        company_name: str,
        city: str = "",
    ) -> dict[str, str] | None:
        """Search DDG for a LinkedIn profile of the company's key person.

        Returns {"name", "role", "linkedin_url"} extracted exclusively from the
        search snippet — never from LLM inference.  Returns None if nothing
        verifiable is found.
        """
        if not company_name.strip():
            return None
        geo = f" {city}" if city else ""
        query = (
            f'"{company_name}"{geo} site:linkedin.com/in '
            f"gerente OR director OR propietario OR socio OR responsable"
        )
        payload = await self.search(run_id="", query=query, max_results=3)
        for result in payload.get("results", []):
            contact = self._extract_contact_from_snippet(result, company_name)
            if contact:
                return contact
        return None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _sync_search(self, query: str, count: int) -> list[dict[str, Any]]:
        try:
            from duckduckgo_search import DDGS  # already in requirements
            with DDGS() as ddgs:
                raw = ddgs.text(query, max_results=count) or []
        except Exception:
            return []
        results = []
        for item in raw:
            href = str(item.get("href") or "").strip()
            if not href:
                continue
            results.append({
                "title": str(item.get("title") or "").strip(),
                "url": href,
                "description": str(item.get("body") or "").strip(),
            })
        return results

    def _extract_contact_from_snippet(
        self, result: dict[str, Any], company_name: str
    ) -> dict[str, str] | None:
        url = result.get("url", "")
        if "linkedin.com/in/" not in url:
            return None

        title = result.get("title", "")
        snippet = result.get("description", "")

        m = _LINKEDIN_TITLE_RE.match(title)
        if not m:
            return None

        name = m.group(1).strip()
        role_raw = _ROLE_CLEANUP_RE.sub("", m.group(2)).strip()

        # Verify: at least one significant word of the company name appears in
        # the combined title+snippet.  This prevents false positives from
        # unrelated LinkedIn profiles.
        company_words = [w for w in company_name.lower().split() if len(w) > 3]
        combined = (title + " " + snippet).lower()
        if company_words and not any(w in combined for w in company_words):
            return None

        if not name or not role_raw:
            return None

        return {"name": name, "role": role_raw, "linkedin_url": url}

    @staticmethod
    def is_directory_domain(url: str) -> bool:
        try:
            hostname = urlparse(url).hostname or ""
            root = ".".join(hostname.split(".")[-2:])
            return hostname in BLOCKED_EXACT_DOMAINS or root in BLOCKED_EXACT_DOMAINS
        except Exception:
            return False
