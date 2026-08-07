"""
app/nexus/utils/geocoding.py
-------------------------------
Resolucion de topónimos a provincia/región reales via Nominatim (OpenStreetMap).

Gratis, sin API key. Uso ligero (una consulta por interpretacion de brief,
no por candidato) — respeta la politica de uso de Nominatim (User-Agent
identificable, sin rafagas).
"""

from __future__ import annotations

import httpx
from loguru import logger

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "NexusProspecting/1.0 (Assets Consultores)"


async def geocode_place(query: str) -> dict | None:
    """Resuelve un nombre de lugar a {name, city, province, region, country}. None si no se encuentra."""
    query = (query or "").strip()
    if not query:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                _NOMINATIM_URL,
                params={"q": query, "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "es"},
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
            results = response.json()
    except Exception:
        logger.exception("geocode_place | fallo consultando Nominatim | query={}", query)
        return None

    if not results:
        return None

    address = results[0].get("address", {})
    city = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("municipality") or query
    )
    return {
        "name": results[0].get("display_name", query),
        "city": city,
        "province": address.get("province") or address.get("county") or "",
        "region": address.get("state") or "",
        "country": address.get("country") or "",
    }
