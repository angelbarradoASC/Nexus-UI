"""Core models for local-first prospecting."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any


@dataclass(slots=True)
class ProspectingBrief:
    """Normalized brief that drives a prospecting run."""

    vertical: str
    target_description: str = ""
    city: str = ""
    province: str = ""
    region: str = ""
    radius_km: int | None = None
    desired_count: int = 20
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    crm_tags: list[str] = field(default_factory=list)
    campaign_type: str = ""
    minimum_score: int = 50
    country: str = "es"
    language: str = "es"
    dry_run: bool = True
    async_mode: bool = False
    represented_by: str = "assets"  # assets | automato | other
    vertical_created: bool = False

    @property
    def geography_label(self) -> str:
        parts = [self.city, self.province, self.region]
        return ", ".join(part for part in parts if part).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical,
            "target_description": self.target_description,
            "city": self.city,
            "province": self.province,
            "region": self.region,
            "radius_km": self.radius_km,
            "desired_count": self.desired_count,
            "must_have": list(self.must_have),
            "nice_to_have": list(self.nice_to_have),
            "exclude": list(self.exclude),
            "crm_tags": list(self.crm_tags),
            "campaign_type": self.campaign_type,
            "minimum_score": self.minimum_score,
            "country": self.country,
            "language": self.language,
            "dry_run": self.dry_run,
            "async_mode": self.async_mode,
            "represented_by": self.represented_by,
            "vertical_created": self.vertical_created,
        }


def default_tags_for_vertical(vertical: str, geography: str = "") -> list[str]:
    vertical = normalize_vertical(vertical)
    geography_tag = geography.lower().replace(" ", "-") if geography else ""
    if vertical == "asesoria":
        tags = ["asesoria", "gestoria", "fiscal", "laboral", "contacto-pendiente", "prospeccion-nexus"]
    elif vertical == "inmobiliaria":
        tags = ["inmobiliaria", "agencia", "contacto-pendiente", "prospeccion-nexus"]
    elif vertical == "public_administration":
        tags = ["ayuntamiento", "administracion-publica", "modernizacion", "contacto-pendiente", "prospeccion-nexus"]
    elif vertical == "restaurants":
        tags = ["restaurante", "hosteleria", "automatizacion", "whatsapp", "reservas", "prospeccion-nexus"]
    elif vertical == "salud":
        tags = ["salud", "clinica", "dentista", "odontologia", "contacto-pendiente", "prospeccion-nexus"]
    else:
        tags = [vertical, "prospeccion-nexus"]
    if geography_tag:
        tags.append(geography_tag)
    return tags
KNOWN_VERTICALS = {
    "asesoria",
    "inmobiliaria",
    "public_administration",
    "restaurants",
    "salud",
}


_VERTICAL_STOPWORDS = {
    "busca",
    "buscar",
    "busquen",
    "dame",
    "encuentra",
    "encuentres",
    "quiero",
    "quieres",
    "necesito",
    "para",
    "con",
    "sin",
    "cerca",
    "zona",
    "radio",
    "km",
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "en",
    "por",
    "y",
    "o",
    "al",
    "a",
}


def _normalize_slug(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", raw) if token]
    tokens = [token for token in tokens if token not in _VERTICAL_STOPWORDS]
    if len(tokens) >= 1:
        return "_".join(tokens[:3])
    return ""


_VERTICAL_HINTS: dict[str, tuple[str, ...]] = {
    "restaurants": ("restauran", "hosteleria", "hostelero", "gastro", "cocina"),
    "asesoria": ("asesor", "gestor", "gestoria", "fiscal", "laboral", "contable"),
    "inmobiliaria": ("inmobiliaria", "inmobiliarias", "inmob", "pisos", "alquiler", "vivienda"),
    "public_administration": ("ayuntamiento", "municipio", "administracion", "concejal"),
    "salud": ("clinic", "dentist", "odont", "salud", "medic"),
}


def _slug_to_canonical(slug: str) -> str | None:
    for canonical, hints in _VERTICAL_HINTS.items():
        if any(hint in slug for hint in hints):
            return canonical
    return None


def normalize_vertical(vertical: str | None, *, fallback_text: str = "") -> str:
    raw = _normalize_slug(vertical or "")
    if raw in KNOWN_VERTICALS:
        return raw
    # Intenta mapear el slug a un vertical canónico por keywords
    canonical = _slug_to_canonical(raw)
    if canonical:
        return canonical
    # Si el slug no encaja con ningún vertical, prueba el texto libre como fallback
    if fallback_text:
        fallback_slug = _normalize_slug(fallback_text)
        if fallback_slug in KNOWN_VERTICALS:
            return fallback_slug
        canonical = _slug_to_canonical(fallback_slug)
        if canonical:
            return canonical
    # Conserva el slug original solo si es significativo y no es ruido del prompt
    if raw and raw != "custom":
        return raw
    return "custom"


def vertical_label(vertical: str) -> str:
    mapping = {
        "asesoria": "Asesorias / Gestorias",
        "inmobiliaria": "Inmobiliarias",
        "public_administration": "Adm. publica",
        "restaurants": "Restaurantes",
        "salud": "Clinicas / Salud",
        "custom": "Custom",
    }
    if vertical in mapping:
        return mapping[vertical]
    return str(vertical or "").replace("_", " ").replace("-", " ").title() or "Custom"
