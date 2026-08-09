"""
app/nexus/utils/geocoding.py
-------------------------------
Resolucion de topónimos a provincia/región reales via Nominatim (OpenStreetMap).

Gratis, sin API key. Uso ligero (una consulta por interpretacion de brief,
no por candidato) — respeta la politica de uso de Nominatim (User-Agent
identificable, sin rafagas).
"""

from __future__ import annotations

import asyncio
import math
import time

import httpx
from loguru import logger

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "NexusProspecting/1.0 (Assets Consultores)"


async def geocode_place(query: str) -> dict | None:
    """Resuelve un nombre de lugar a {name, city, province, region, country, lat, lon}. None si no se encuentra."""
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

    hit = results[0]
    address = hit.get("address", {})
    city = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("municipality") or query
    )
    try:
        lat = float(hit["lat"]) if hit.get("lat") is not None else None
        lon = float(hit["lon"]) if hit.get("lon") is not None else None
    except (TypeError, ValueError):
        lat = lon = None
    return {
        "name": hit.get("display_name", query),
        "city": city,
        "province": address.get("province") or address.get("county") or "",
        "region": address.get("state") or "",
        "country": address.get("country") or "",
        "lat": lat,
        "lon": lon,
    }


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en linea recta (km) entre dos coordenadas."""
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


class GeocodeCache:
    """Cachea geocode_place() y respeta el limite de ~1 req/s de Nominatim.

    Pensado para geocodificar direcciones de candidatos dentro de un mismo run
    de prospeccion sin re-consultar la misma ciudad decenas de veces ni saturar
    la API gratuita.
    """

    def __init__(self, *, rate_limit_seconds: float = 1.0) -> None:
        self._cache: dict[str, dict | None] = {}
        self._lock = asyncio.Lock()
        self._rate_limit_seconds = rate_limit_seconds
        self._last_call = 0.0

    async def resolve(self, query: str) -> dict | None:
        key = (query or "").strip().lower()
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        async with self._lock:
            if key in self._cache:  # ya resuelto mientras esperabamos el lock
                return self._cache[key]
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._rate_limit_seconds:
                await asyncio.sleep(self._rate_limit_seconds - elapsed)
            result = await geocode_place(key)
            self._last_call = time.monotonic()
            self._cache[key] = result
            return result
