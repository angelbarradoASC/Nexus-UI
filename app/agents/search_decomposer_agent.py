"""SearchDecomposerAgent — convierte texto libre en un search intent estructurado.

Standalone. No modifica nada del pipeline existente.
Se conecta al sistema existente cuando se incorpore en la Fase 3.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from loguru import logger

from agents.llm_router import get_router
from nexus.prompts import resolve_prompt_sync
from nexus.utils.llm_json import parse_llm_json


# ── Cadenas conocidas por sector ─────────────────────────────────────────────

_KNOWN_CHAINS: dict[str, list[str]] = {
    "salud": [
        "Vitaldent", "Sanitas Dental", "Clínica Baviera", "Dentix", "Asisa Dental",
        "Mapfre Dental", "Impress", "Orthodontic", "iDental", "MediDent",
        "Clínica Dental Lacer", "DenClinic", "Sonrisas & Sonrisas",
    ],
    "inmobiliaria": [
        "RE/MAX", "Century 21", "Engel & Völkers", "Coldwell Banker", "ERA",
        "Housfy", "Tecnocasa", "Donpiso", "Fincas Corral", "Alfa Inmobiliaria",
    ],
    "asesoria": [
        "Gestoría Henares", "Agestión", "Serfisco", "BBVA Asesoría",
    ],
    "restaurants": [
        "McDonald's", "Burger King", "KFC", "Domino's", "Telepizza",
        "TGB", "Vips", "Foster's Hollywood",
    ],
}

_KNOWN_INCLUSION_CRITERIA = {
    "has_email", "has_phone", "has_own_website", "has_address", "has_linkedin",
}
_KNOWN_EXCLUSION_CRITERIA = {
    "not_chain", "not_directory", "not_franchise", "not_generic_brand",
}

# ── Fallback heurístico ───────────────────────────────────────────────────────

def _sector_from_text(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("dental", "dentista", "odont", "clinica", "clínica", "salud", "fisio", "medico", "médico")):
        return "salud"
    if any(w in t for w in ("asesor", "gestor", "fiscal", "laboral", "contable")):
        return "asesoria"
    if any(w in t for w in ("inmobiliaria", "pisos", "alquiler", "vivienda")):
        return "inmobiliaria"
    if any(w in t for w in ("restaurante", "hostelería", "bar ", "cafetería")):
        return "restaurants"
    if any(w in t for w in ("ayuntamiento", "administración", "municipio")):
        return "public_administration"
    return "custom"


def _sub_sector_from_text(text: str, sector: str) -> str | None:
    t = text.lower()
    if sector == "salud":
        if any(w in t for w in ("dental", "dentista", "odont")):
            return "dental"
        if any(w in t for w in ("fisio", "fisioterapia")):
            return "fisioterapia"
        if any(w in t for w in ("dermato", "piel")):
            return "dermatologia"
        if any(w in t for w in ("psicolog", "psiquiat")):
            return "psicologia"
    if sector == "asesoria":
        if any(w in t for w in ("fiscal", "tributar", "irpf", "renta")):
            return "fiscal"
        if any(w in t for w in ("laboral", "nomina", "autónomo")):
            return "laboral"
    return None


def _business_type_from_text(text: str, sector: str, sub_sector: str | None) -> str:
    t = text.lower()
    if sub_sector == "dental":
        return "clínica dental"
    if sub_sector == "fisioterapia":
        return "clínica de fisioterapia"
    if sector == "salud":
        for w in ("clínica", "clinica", "consulta", "centro médico"):
            if w in t:
                return f"{w} médica"
        return "clínica médica"
    if sector == "asesoria":
        return "asesoría" + (f" {sub_sector}" if sub_sector else "")
    if sector == "inmobiliaria":
        return "agencia inmobiliaria"
    if sector == "restaurants":
        return "restaurante"
    if sector == "public_administration":
        return "organismo público"
    return text.strip()[:60]


def _extract_location(text: str) -> dict[str, Any]:
    import re
    city = None
    province = None
    radius_km = None

    radius_match = re.search(r'\b(\d+)\s*km\b', text, re.IGNORECASE)
    if radius_match:
        radius_km = int(radius_match.group(1))

    prep_hits = re.findall(
        r'\b(?:en|cerca de|ciudad de|municipio de)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]+)?)',
        text,
    )
    cap_hits = re.findall(r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})\b', text)

    _STOP = {"busca", "quiero", "necesito", "dame", "encuentra", "clinica", "clínica",
             "dental", "dentista", "cadena", "cadenas", "correo", "email", "tiene",
             "tengan", "sean", "que", "con", "sin", "una", "para"}

    candidates = []
    for raw in prep_hits + cap_hits:
        normalized = raw.strip().title()
        if normalized.lower() not in _STOP and len(normalized) > 2:
            candidates.append(normalized)

    if candidates:
        city = candidates[0]
    if len(candidates) > 1:
        province = candidates[1]

    pop_context = None
    _CAPITALS = {"Madrid", "Barcelona", "Valencia", "Sevilla", "Zaragoza", "Málaga",
                 "Murcia", "Palma", "Las Palmas", "Bilbao", "Alicante", "Córdoba",
                 "Valladolid", "Vigo", "Gijón", "Granada", "Oviedo", "A Coruña",
                 "Vitoria", "Pamplona", "Santander", "Logroño", "Burgos", "Salamanca",
                 "Toledo", "Lleida", "Tarragona", "Girona", "Badajoz", "Cáceres",
                 "Mérida", "Huelva", "Albacete", "Ciudad Real", "Cuenca", "Guadalajara",
                 "Segovia", "Ávila", "Soria", "Zamora", "León", "Palencia", "Lugo",
                 "Ourense", "Pontevedra", "Teruel", "Huesca", "Lérida"}
    if city in _CAPITALS:
        pop_context = "capital de provincia"

    return {
        "city": city,
        "province": province or city,
        "region": None,
        "radius_km": radius_km,
        "population_context": pop_context,
    }


def _extract_inclusions(text: str) -> list[dict[str, Any]]:
    t = text.lower()
    inclusions = []
    if any(w in t for w in ("correo", "email", "mail", "e-mail")):
        inclusions.append({
            "criterion": "has_email",
            "description": "debe tener email directo visible",
            "check_method": "scrape_web",
        })
    if any(w in t for w in ("teléfono", "telefono", "tlf", "tel ")):
        inclusions.append({
            "criterion": "has_phone",
            "description": "debe tener teléfono de contacto",
            "check_method": "scrape_web",
        })
    if any(w in t for w in ("web propia", "página propia", "web")):
        inclusions.append({
            "criterion": "has_own_website",
            "description": "debe tener web propia (no directorio)",
            "check_method": "domain_check",
        })
    return inclusions


def _extract_exclusions(text: str, sector: str) -> list[dict[str, Any]]:
    t = text.lower()
    exclusions = []
    if any(w in t for w in ("cadena", "cadenas", "franquicia", "franquicias", "grupo", "grupos", "corporativa")):
        exclusions.append({
            "criterion": "not_chain",
            "description": "no debe ser cadena, franquicia ni grupo corporativo",
            "check_method": "name_check+domain_check+llm",
            "known_examples": _KNOWN_CHAINS.get(sector, []),
        })
    if any(w in t for w in ("directorio", "agregador", "portal")):
        exclusions.append({
            "criterion": "not_directory",
            "description": "no debe ser un directorio o portal de listados",
            "check_method": "domain_check",
            "known_examples": [],
        })
    return exclusions


def _build_search_queries(business_type: str, location: dict[str, Any], sector: str) -> list[str]:
    city = location.get("city") or ""
    geo = city or location.get("province") or "España"

    base_queries = {
        "salud": [
            f"clínica dental {geo}",
            f"dentista {geo}",
            f"odontología {geo}",
            f"clínica odontológica {geo}",
        ],
        "asesoria": [
            f"asesoría fiscal {geo}",
            f"gestoría {geo}",
            f"asesoría laboral {geo}",
        ],
        "inmobiliaria": [
            f"inmobiliaria {geo}",
            f"agencia inmobiliaria {geo}",
        ],
        "restaurants": [
            f"restaurante {geo}",
            f"restaurante {geo} reservas",
        ],
        "public_administration": [
            f"ayuntamiento {geo}",
            f"administración pública {geo}",
        ],
    }

    queries = base_queries.get(sector, [f"{business_type} {geo}", f"{business_type} {geo} contacto"])
    return queries[:4]


def _fallback_decompose(text: str) -> dict[str, Any]:
    sector = _sector_from_text(text)
    sub_sector = _sub_sector_from_text(text, sector)
    business_type = _business_type_from_text(text, sector, sub_sector)
    location = _extract_location(text)
    inclusions = _extract_inclusions(text)
    exclusions = _extract_exclusions(text, sector)
    search_queries = _build_search_queries(business_type, location, sector)
    guardrail_criteria = [i["criterion"] for i in inclusions] + [e["criterion"] for e in exclusions]

    return {
        "business_type": business_type,
        "sector": sector,
        "sub_sector": sub_sector,
        "location": location,
        "inclusions": inclusions,
        "exclusions": exclusions,
        "search_queries": search_queries,
        "guardrail_criteria": guardrail_criteria,
        "confidence": 0.55,
        "assumptions_made": ["interpretado por heurísticas — LLM no disponible"],
        "ambiguities": [],
        "_fallback": True,
    }


# ── Agente principal ──────────────────────────────────────────────────────────

class SearchDecomposerAgent:
    """Convierte una petición en lenguaje natural en un search intent estructurado.

    Uso:
        agent = SearchDecomposerAgent()
        result = await agent.decompose("clínicas dentales de Zaragoza con correo, no cadenas")
    """

    async def decompose(
        self,
        text: str,
        *,
        requested_by: str = "anonymous",
    ) -> dict[str, Any]:
        """Descompone el texto y devuelve un search intent con trazabilidad."""
        if not text or not text.strip():
            raise ValueError("text is required")

        request_id = f"sreq-{uuid4().hex[:10]}"
        requested_at = datetime.now(timezone.utc).isoformat()

        intent = await self._run_llm(text)
        if intent is None:
            logger.warning("decomposer | LLM no disponible — usando fallback heurístico")
            intent = _fallback_decompose(text)

        intent = self._enrich_known_chains(intent)
        intent = self._normalize_guardrail_criteria(intent)

        return {
            "request_id": request_id,
            "requested_by": requested_by,
            "requested_at": requested_at,
            "original_text": text.strip(),
            "search_intent": intent,
            "pipeline_version": "1.0",
        }

    async def _run_llm(self, text: str) -> dict[str, Any] | None:
        try:
            import asyncio
            llm = get_router()
            response = await asyncio.wait_for(
                llm.call(
                    messages=[
                        {"role": "system", "content": resolve_prompt_sync("sales.prospecting.decompose")},
                        {"role": "user", "content": text.strip()},
                    ],
                    preferred_level=1,
                    temperature=0.1,
                    max_tokens=800,
                    timeout=8.0,
                ),
                timeout=12.0,
            )
        except Exception as exc:
            logger.warning("decomposer | LLM error: {}", exc)
            return None

        if response is None or response.error:
            return None

        parsed = parse_llm_json(response.content or "")
        if parsed is None:
            return None

        required = {"business_type", "sector", "location", "search_queries", "guardrail_criteria"}
        if not required.issubset(parsed.keys()):
            logger.warning("decomposer | LLM devolvió JSON incompleto — fallback")
            return None

        return parsed

    def _enrich_known_chains(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Rellena known_examples con la lista interna si el LLM los dejó vacíos."""
        sector = intent.get("sector", "custom")
        for excl in intent.get("exclusions", []):
            if excl.get("criterion") == "not_chain" and not excl.get("known_examples"):
                excl["known_examples"] = _KNOWN_CHAINS.get(sector, [])
        return intent

    def _normalize_guardrail_criteria(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Asegura que guardrail_criteria es consistente con inclusions + exclusions."""
        from_inclusions = [i["criterion"] for i in intent.get("inclusions", [])]
        from_exclusions = [e["criterion"] for e in intent.get("exclusions", [])]
        declared = list(intent.get("guardrail_criteria", []))
        merged = list(dict.fromkeys(from_inclusions + from_exclusions + declared))
        intent["guardrail_criteria"] = merged
        return intent
