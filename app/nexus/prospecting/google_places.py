"""Google Places (New) Text Search client for prospecting discovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.internationalPhoneNumber,"
    "places.websiteUri,"
    "places.types,"
    "places.rating,"
    "places.userRatingCount"
)

# Las plantillas de query por vertical (query_template, includedType | None) ya
# no viven aqui — se cargan desde sales_verticals.discovery_config['places_queries']
# (ver SalesVerticalsRepository) y se pasan a search_by_brief() como parametro.
# Si la vertical no trae plantillas curadas, el fallback generico de abajo usa
# lo que el usuario pidio de verdad (target_description), no la etiqueta de
# clasificacion — clasificar y buscar son cosas distintas.


@dataclass(slots=True)
class GooglePlacesSettings:
    api_key: str | None
    enabled: bool = False
    rate_limit_seconds: float = 0.5
    timeout: float = 15.0
    max_results_per_query: int = 20


class GooglePlacesClient:
    """Google Places (New) Text Search for structured B2B discovery."""

    def __init__(self, *, settings: GooglePlacesSettings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled and self._settings.api_key)

    async def search_by_brief(
        self,
        *,
        vertical: str,
        geography: str,
        max_results: int = 20,
        language: str = "es",
        target_description: str = "",
        places_queries: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search Places for all query templates of a vertical and deduplicate.

        Returns (results, api_calls_made) so the caller can track budget.
        """
        if not self.enabled or not geography:
            return [], 0

        # Sin plantilla curada para este vertical: la busqueda usa lo que el
        # usuario pidio de verdad (target_description), no la etiqueta de
        # clasificacion ("custom", un slug feo, etc.) — clasificar y buscar
        # son cosas distintas.
        fallback_term = target_description.strip() or vertical
        if places_queries:
            templates = [(q["template"], q.get("included_type")) for q in places_queries]
        else:
            templates = [(f"{{geo}} {fallback_term}", None)]
        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        api_calls = 0

        for template, included_type in templates:
            if len(collected) >= max_results:
                break
            query = template.replace("{geo}", geography).strip()
            hits = await self._search(
                query=query,
                included_type=included_type,
                max_results=min(max_results, self._settings.max_results_per_query),
                language=language,
            )
            api_calls += 1
            for hit in hits:
                pid = hit.get("place_id", "")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                collected.append(hit)

        return collected[:max_results], api_calls

    async def _search(
        self,
        *,
        query: str,
        included_type: str | None,
        max_results: int,
        language: str,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "textQuery": query,
            "maxResultCount": max(1, min(max_results, 20)),
            "languageCode": language,
        }
        if included_type:
            body["includedType"] = included_type

        async with self._lock:
            try:
                async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                    response = await client.post(
                        _PLACES_URL,
                        headers={
                            "Content-Type": "application/json",
                            "X-Goog-Api-Key": str(self._settings.api_key),
                            "X-Goog-FieldMask": _FIELD_MASK,
                        },
                        json=body,
                    )
                    response.raise_for_status()
                    raw = response.json()
            except Exception:
                return []
            await asyncio.sleep(max(self._settings.rate_limit_seconds, 0.0))

        results: list[dict[str, Any]] = []
        for place in raw.get("places", []):
            name = (place.get("displayName") or {}).get("text", "")
            website = (place.get("websiteUri") or "").rstrip("/")
            phone = place.get("internationalPhoneNumber", "")
            address = place.get("formattedAddress", "")
            rating = place.get("rating")
            rating_count = place.get("userRatingCount", 0)

            results.append({
                "place_id": place.get("id", ""),
                "title": name,
                "url": website,
                "description": address,
                "phone": phone,
                "address": address,
                "rating": rating,
                "rating_count": rating_count,
                "google_types": place.get("types", []),
                "source": "google_places",
            })

        return results
