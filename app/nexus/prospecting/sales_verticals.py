"""BBDD-backed sales verticals — sustituye el hardcoding de verticales/aliases/scoring
que antes vivia en if/elif de Python (models.py, service.py, extractors.py,
google_places.py). Reutiliza el mismo SQLiteStore/prospecting.sqlite3 que ya usa
ProspectingRepository, sin infraestructura nueva.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.persistence.prospecting_schema import ensure_prospecting_schema
from nexus.persistence.sqlite_store import SQLiteStore

FALLBACK_SLUG = "custom"

_SLUG_STOPWORDS = {
    "busca", "buscar", "busquen", "dame", "encuentra", "encuentres", "quiero",
    "quieres", "necesito", "para", "con", "sin", "cerca", "zona", "radio",
    "km", "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "en", "por", "y", "o", "al", "a",
}


def normalize_slug(value: str) -> str:
    """Misma normalizacion que antes vivia en models.py: quita acentos, tokeniza,
    descarta stopwords y se queda con los primeros 3 tokens unidos por '_'.
    """
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", raw) if token]
    tokens = [token for token in tokens if token not in _SLUG_STOPWORDS]
    if tokens:
        return "_".join(tokens[:3])
    return ""


def normalize_full_text(value: str) -> str:
    """Accent-strip + lowercase, sin tokenizar ni truncar — para matching por
    substring contra frases largas (a diferencia de normalize_slug, que solo
    se queda con los primeros 3 tokens tras quitar stopwords).
    """
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(raw.lower().split())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DuplicateVerticalError(ValueError):
    """Slug o alias ya usado por otra vertical."""


class VerticalNotFoundError(ValueError):
    """No existe ninguna vertical con ese slug."""


class ProtectedVerticalError(ValueError):
    """La vertical fallback (custom) no se puede borrar."""


@dataclass(slots=True)
class SalesVertical:
    slug: str
    nombre: str
    aliases: list[str] = field(default_factory=list)
    activo: bool = True
    is_fallback: bool = False
    scoring_rules: dict[str, Any] = field(default_factory=dict)
    discovery_config: dict[str, Any] = field(default_factory=dict)
    crm_tags: list[str] = field(default_factory=list)
    crm_sector: str = "otros"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "nombre": self.nombre,
            "aliases": list(self.aliases),
            "activo": self.activo,
            "is_fallback": self.is_fallback,
            "scoring_rules": dict(self.scoring_rules),
            "discovery_config": dict(self.discovery_config),
            "crm_tags": list(self.crm_tags),
            "crm_sector": self.crm_sector,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_row(row: Any) -> "SalesVertical":
        return SalesVertical(
            slug=row["slug"],
            nombre=row["nombre"],
            aliases=json.loads(row["aliases_json"] or "[]"),
            activo=bool(row["activo"]),
            is_fallback=bool(row["is_fallback"]),
            scoring_rules=json.loads(row["scoring_rules_json"] or "{}"),
            discovery_config=json.loads(row["discovery_config_json"] or "{}"),
            crm_tags=json.loads(row["crm_tags_json"] or "[]"),
            crm_sector=row["crm_sector"] or "otros",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def default_tags(self, geography: str = "") -> list[str]:
        tags = list(self.crm_tags)
        geography_tag = geography.lower().replace(" ", "-") if geography else ""
        if geography_tag:
            tags.append(geography_tag)
        return tags


# ── Seed: migracion 1:1 de lo que antes estaba hardcodeado en Python ──────────
# Cada entrada preserva EXACTAMENTE las senales/plantillas que tenian los
# if/elif de models.py, service.py, extractors.py y google_places.py.

_RESTAURANT_LINK_HINTS = ["contacto", "contact", "reservas", "reservation", "menu", "carta", "eventos", "about", "legal"]
_PUBLIC_LINK_HINTS = ["contacto", "contact", "corporacion", "corporación", "concejal", "transparencia", "secretaria", "equipo"]
_RESTAURANT_QUALITY_TOKENS = [
    "menu degustacion", "eventos", "grupos", "terraza", "reservas",
    "tripadvisor", "thefork", "instagram", "cena de empresa",
]
_GENERIC_QUALITY_TOKENS = [
    "administracion electronica", "sede electronica", "nuevas tecnologias",
    "transformacion digital", "modernizacion", "transparencia",
]
_GENERIC_DDG_TEMPLATES = ["{target} {geo} contacto", "{target} {geo} email teléfono"]

# ── point_criteria: scoring por puntos, antes hardcodeado en 5 metodos
# _score_* de ProspectScorer (app/nexus/prospecting/scoring.py). Migracion
# 1:1 de esos pesos — ver docs/scoring.md para el vocabulario de cada campo.
# _GENERIC_POINT_CRITERIA es el fallback real para "custom" y cualquier
# vertical sin criterio propio (zapaterias, talleres, o una vertical nueva
# creada desde la API) — antes esas verticales heredaban por accidente los
# pesos de "administracion publica" via el `else` del if/elif.
_GENERIC_POINT_CRITERIA: dict[str, Any] = {
    "has_website": 20, "official_website": 0, "dns_valid": 10, "mx_valid": 10,
    "email_points": 15, "email_requires_direct": False,
    "phone": 15, "contact_form_only_bonus": 0,
    "contact_role_keywords": 0, "contact_person": 0,
    "rating_high_points": 10, "rating_high_threshold": 4.0,
    "rating_mid_points": 5, "rating_mid_threshold": 3.5,
    "social_links_per_item": 4, "social_links_max": 12,
    "quality_signals_per_item": 5, "quality_signals_max": 10,
    "premium_bonus": 0, "contact_form_only_penalty": 0, "crm_duplicate_penalty": 25,
}

_RESTAURANT_POINT_CRITERIA: dict[str, Any] = {
    "has_website": 15, "official_website": 0, "dns_valid": 10, "mx_valid": 10,
    "email_points": 15, "email_requires_direct": False,
    "phone": 10, "contact_form_only_bonus": 5,
    "contact_role_keywords": 0, "contact_person": 0,
    "rating_high_points": 0, "rating_high_threshold": 4.0,
    "rating_mid_points": 0, "rating_mid_threshold": 3.5,
    "social_links_per_item": 4, "social_links_max": 12,
    "quality_signals_per_item": 6, "quality_signals_max": 24,
    "premium_bonus": 8, "contact_form_only_penalty": 0, "crm_duplicate_penalty": 25,
}

_ASESORIA_POINT_CRITERIA: dict[str, Any] = {
    "has_website": 20, "official_website": 0, "dns_valid": 10, "mx_valid": 15,
    "email_points": 15, "email_requires_direct": True,
    "phone": 15, "contact_form_only_bonus": 0,
    "contact_role_keywords": 0, "contact_person": 5,
    "rating_high_points": 10, "rating_high_threshold": 4.0,
    "rating_mid_points": 5, "rating_mid_threshold": 3.5,
    "social_links_per_item": 0, "social_links_max": 0,
    "quality_signals_per_item": 5, "quality_signals_max": 10,
    "premium_bonus": 0, "contact_form_only_penalty": 10, "crm_duplicate_penalty": 25,
}

_INMOBILIARIA_SALUD_POINT_CRITERIA: dict[str, Any] = {
    "has_website": 20, "official_website": 0, "dns_valid": 10, "mx_valid": 10,
    "email_points": 15, "email_requires_direct": False,
    "phone": 15, "contact_form_only_bonus": 0,
    "contact_role_keywords": 0, "contact_person": 0,
    "rating_high_points": 10, "rating_high_threshold": 4.0,
    "rating_mid_points": 5, "rating_mid_threshold": 3.5,
    "social_links_per_item": 4, "social_links_max": 12,
    "quality_signals_per_item": 5, "quality_signals_max": 10,
    "premium_bonus": 0, "contact_form_only_penalty": 0, "crm_duplicate_penalty": 25,
}

_PUBLIC_ADMINISTRATION_POINT_CRITERIA: dict[str, Any] = {
    "has_website": 20, "official_website": 10, "dns_valid": 10, "mx_valid": 15,
    "email_points": 15, "email_requires_direct": True,
    "phone": 10, "contact_form_only_bonus": 0,
    "contact_role_keywords": 10, "contact_person": 5,
    "rating_high_points": 0, "rating_high_threshold": 4.0,
    "rating_mid_points": 0, "rating_mid_threshold": 3.5,
    "social_links_per_item": 0, "social_links_max": 0,
    "quality_signals_per_item": 5, "quality_signals_max": 15,
    "premium_bonus": 0, "contact_form_only_penalty": 10, "crm_duplicate_penalty": 25,
}
_INMOBILIARIA_EXCLUSIONS = (
    "-site:idealista.com -site:fotocasa.es -site:pisos.com "
    "-site:habitaclia.com -site:yaencontre.com -site:indomio.es "
    "-site:globaliza.com -site:trovimap.com"
)

_DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "slug": "restaurants", "nombre": "Restaurantes",
        "aliases": ["restauran", "hosteleria", "hostelero", "gastro", "cocina"],
        "scoring_rules": {
            "relevance_signals": ["restaurante", "cocina", "reservas"],
            "premium_signals": ["degustacion", "gourmet", "estrella", "eventos", "reservas", "terraza"],
            "reason_relevant": "restaurante con señales de calidad",
            "reason_irrelevant": "no parece restaurante objetivo",
            "organization_type": "restaurant",
            "requires_direct_contact": True,
            "point_criteria": _RESTAURANT_POINT_CRITERIA,
        },
        "discovery_config": {
            "ddg_templates": [
                "mejores restaurantes {geo} email contacto",
                "restaurante alta cocina {geo} reservas contacto",
                "restaurante eventos empresa {geo} contacto",
                "restaurante gourmet {geo} reservas email",
                "restaurante {geo} cenas empresa",
                "restaurante {geo} terraza reservas",
                "restaurante {geo} carta degustacion reservas",
            ],
            "places_queries": [
                {"template": "restaurante {geo}", "included_type": "restaurant"},
                {"template": "restaurante eventos empresa {geo}", "included_type": "restaurant"},
                {"template": "restaurante gourmet {geo}", "included_type": "restaurant"},
            ],
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _RESTAURANT_QUALITY_TOKENS,
        },
        "crm_tags": ["restaurante", "hosteleria", "automatizacion", "whatsapp", "reservas", "prospeccion-nexus"],
        "crm_sector": "otros",
    },
    {
        "slug": "asesoria", "nombre": "Asesorias / Gestorias",
        "aliases": ["asesor", "gestor", "gestoria", "fiscal", "laboral", "contable"],
        "scoring_rules": {
            "relevance_signals": ["asesoría", "asesoria", "gestoría", "gestoria", "fiscal", "laboral", "contabilidad", "irpf", "renta", "impuesto", "autonomos"],
            "reason_relevant": "asesoría/gestoría con señales fiscales o laborales",
            "reason_irrelevant": "no parece asesoría objetivo",
            "organization_type": "asesoria",
            "requires_direct_contact": True,
            "point_criteria": _ASESORIA_POINT_CRITERIA,
        },
        "discovery_config": {
            "places_queries": [
                {"template": "asesoría fiscal {geo}", "included_type": "accounting"},
                {"template": "gestoría {geo}", "included_type": "accounting"},
                {"template": "asesoría laboral {geo}", "included_type": None},
                {"template": "asesoría contable {geo}", "included_type": "accounting"},
            ],
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
            "blocked_hint_prefixes": [
                "expansion.com/directorio", "einforma.", "axesor.", "infocif.",
                "empresite.", "gestorias.es", "asesoriasempresa.es",
                "gestoriasonline.", "directoriogestoria.",
            ],
        },
        "crm_tags": ["asesoria", "gestoria", "fiscal", "laboral", "contacto-pendiente", "prospeccion-nexus"],
        "crm_sector": "asesoria",
    },
    {
        "slug": "inmobiliaria", "nombre": "Inmobiliarias",
        "aliases": ["inmobiliaria", "inmobiliarias", "inmob", "pisos", "alquiler", "vivienda"],
        "scoring_rules": {
            "relevance_signals": ["inmobiliaria", "agencia", "pisos", "alquiler", "venta", "propiedades", "casas", "fincas", "chalets"],
            "reason_relevant": "inmobiliaria con señales de ventas/alquiler",
            "reason_irrelevant": "no parece inmobiliaria",
            "organization_type": "inmobiliaria",
            "requires_direct_contact": True,
            "point_criteria": _INMOBILIARIA_SALUD_POINT_CRITERIA,
        },
        "discovery_config": {
            "ddg_templates": [
                f"\"inmobiliaria\" \"{{geo}}\" contacto {_INMOBILIARIA_EXCLUSIONS}",
                f"\"agencia inmobiliaria\" \"{{geo}}\" email telefono {_INMOBILIARIA_EXCLUSIONS}",
                f"intitle:inmobiliaria \"{{geo}}\" nosotros contacto {_INMOBILIARIA_EXCLUSIONS}",
                f"\"inmobiliaria\" \"{{geo}}\" \"aviso legal\" {_INMOBILIARIA_EXCLUSIONS}",
                f"\"inmobiliaria\" \"{{geo}}\" \"equipo\" {_INMOBILIARIA_EXCLUSIONS}",
            ],
            "places_queries": [
                {"template": "inmobiliaria {geo}", "included_type": "real_estate_agency"},
                {"template": "agencia inmobiliaria {geo}", "included_type": "real_estate_agency"},
            ],
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
            "blocked_hint_prefixes": [
                "fotocasa.", "idealista.", "pisos.com", "habitaclia.",
                "yaencontre.", "indomio.", "globaliza.", "trovimap.",
                "milanuncios.", "thinkspain.", "kyero.", "nestoria.",
            ],
            "blocked_listing_phrases": ["portal inmobiliario", "anuncios de pisos", "buscador de viviendas"],
        },
        "crm_tags": ["inmobiliaria", "agencia", "contacto-pendiente", "prospeccion-nexus"],
        "crm_sector": "inmobiliaria",
    },
    {
        "slug": "public_administration", "nombre": "Adm. publica",
        "aliases": ["ayuntamiento", "municipio", "administracion", "concejal"],
        "scoring_rules": {
            "relevance_signals": ["ayuntamiento", "sede electrónica", "administración", "concejal", "secretar"],
            "domain_suffix_relevant": ".es",
            "official_website_if_relevant": True,
            "reason_relevant": "organismo público con señales oficiales",
            "reason_irrelevant": "no parece organismo oficial",
            "organization_type": "public_body",
            "point_criteria": _PUBLIC_ADMINISTRATION_POINT_CRITERIA,
        },
        "discovery_config": {
            "ddg_templates": [
                "ayuntamiento {geo} contacto tecnología",
                "sede electrónica {geo} ayuntamiento contacto",
                "concejalía nuevas tecnologías {geo}",
                "secretaría ayuntamiento {geo} contacto",
                "{target} {geo}",
            ],
            "default_target": "ayuntamiento administración electrónica contacto",
            "places_queries": [
                {"template": "ayuntamiento {geo}", "included_type": "local_government_office"},
                {"template": "administración local {geo}", "included_type": "local_government_office"},
            ],
            "link_hints": _PUBLIC_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
        },
        "crm_tags": ["ayuntamiento", "administracion-publica", "modernizacion", "contacto-pendiente", "prospeccion-nexus"],
        "crm_sector": "otros",
    },
    {
        "slug": "salud", "nombre": "Clinicas / Salud",
        "aliases": ["clinic", "dentist", "odont", "salud", "medic"],
        "scoring_rules": {
            "organization_type": "custom",
            "requires_direct_contact": True,
            "point_criteria": _INMOBILIARIA_SALUD_POINT_CRITERIA,
        },
        "discovery_config": {
            "ddg_templates": [
                "clinica dental {geo} contacto",
                "dentista {geo} email telefono",
                "odontologo {geo} contacto",
                "clinica odontologica {geo} contacto",
                "salud dental {geo} contacto",
            ],
            "places_queries": [
                {"template": "clínica dental {geo}", "included_type": None},
                {"template": "dentista {geo}", "included_type": None},
                {"template": "odontólogo {geo}", "included_type": None},
            ],
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
        },
        "crm_tags": ["salud", "clinica", "dentista", "odontologia", "contacto-pendiente", "prospeccion-nexus"],
        "crm_sector": "salud",
    },
    {
        "slug": "zapaterias", "nombre": "Zapaterias",
        "aliases": ["zapater", "calzado", "zapato"],
        "scoring_rules": {"organization_type": "custom", "point_criteria": dict(_GENERIC_POINT_CRITERIA)},
        "discovery_config": {
            "ddg_templates": list(_GENERIC_DDG_TEMPLATES),
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
        },
        "crm_tags": ["zapaterias", "prospeccion-nexus"],
        "crm_sector": "otros",
    },
    {
        "slug": "talleres", "nombre": "Talleres / Automocion",
        "aliases": ["taller", "mecanico", "automocion", "neumatico", "coches", "chapa y pintura"],
        "scoring_rules": {"organization_type": "custom", "point_criteria": dict(_GENERIC_POINT_CRITERIA)},
        "discovery_config": {
            "ddg_templates": list(_GENERIC_DDG_TEMPLATES),
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
        },
        "crm_tags": ["talleres", "prospeccion-nexus"],
        "crm_sector": "otros",
    },
    {
        "slug": FALLBACK_SLUG, "nombre": "Otros",
        "aliases": [],
        "is_fallback": True,
        "scoring_rules": {"organization_type": "custom", "point_criteria": dict(_GENERIC_POINT_CRITERIA)},
        "discovery_config": {
            "ddg_templates": list(_GENERIC_DDG_TEMPLATES),
            "link_hints": _RESTAURANT_LINK_HINTS,
            "quality_signal_tokens": _GENERIC_QUALITY_TOKENS,
        },
        # El CRM real ya tiene leads con el tag "otros" (nombre historico de este
        # fallback) — se conserva el tag tal cual aunque el slug ahora sea "custom".
        "crm_tags": ["otros", "prospeccion-nexus"],
        "crm_sector": "otros",
    },
]


class SalesVerticalsRepository:
    """CRUD + resolucion de verticales comerciales, persistido en SQLite.

    Sincrono a proposito: sqlite3 local no se beneficia de async/await, y
    generate_queries/_heuristic_classification (que la consultan) tampoco lo son.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(os.environ.get("NEXUS_PROSPECTING_DB_PATH") or (self._data_dir / "prospecting.sqlite3"))
        self._store = SQLiteStore(db_path)
        ensure_prospecting_schema(self._store)
        self._seed_defaults_if_empty()
        self._backfill_point_criteria_if_missing()

    def _seed_defaults_if_empty(self) -> None:
        with self._store.transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM sales_verticals").fetchone()
            if row["c"]:
                return
            now = _now_iso()
            for seed in _DEFAULT_SEED:
                conn.execute(
                    """
                    INSERT INTO sales_verticals(
                        slug, nombre, aliases_json, activo, is_fallback,
                        scoring_rules_json, discovery_config_json, crm_tags_json,
                        crm_sector, created_at, updated_at
                    ) VALUES(?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seed["slug"],
                        seed["nombre"],
                        json.dumps(seed["aliases"], ensure_ascii=False),
                        1 if seed.get("is_fallback") else 0,
                        json.dumps(seed["scoring_rules"], ensure_ascii=False),
                        json.dumps(seed["discovery_config"], ensure_ascii=False),
                        json.dumps(seed["crm_tags"], ensure_ascii=False),
                        seed["crm_sector"],
                        now,
                        now,
                    ),
                )

    def _backfill_point_criteria_if_missing(self) -> None:
        """Instalaciones que ya tenian sales_verticals sembrada antes de que
        existiera point_criteria no lo reciben via _seed_defaults_if_empty
        (solo siembra si la tabla esta vacia). Migracion idempotente: solo
        escribe las filas a las que de verdad les falta el campo."""
        seed_point_criteria = {
            seed["slug"]: seed.get("scoring_rules", {}).get("point_criteria")
            for seed in _DEFAULT_SEED
        }
        with self._store.transaction() as conn:
            rows = conn.execute("SELECT slug, scoring_rules_json FROM sales_verticals").fetchall()
            now = _now_iso()
            for row in rows:
                rules = json.loads(row["scoring_rules_json"] or "{}")
                if "point_criteria" in rules:
                    continue
                rules["point_criteria"] = seed_point_criteria.get(row["slug"]) or dict(_GENERIC_POINT_CRITERIA)
                conn.execute(
                    "UPDATE sales_verticals SET scoring_rules_json = ?, updated_at = ? WHERE slug = ?",
                    (json.dumps(rules, ensure_ascii=False), now, row["slug"]),
                )

    # ── Lectura ─────────────────────────────────────────────────────────────

    def list_all(self) -> list[SalesVertical]:
        with self._store.connect() as conn:
            rows = conn.execute("SELECT * FROM sales_verticals ORDER BY is_fallback ASC, nombre ASC").fetchall()
        return [SalesVertical.from_row(row) for row in rows]

    def list_active(self) -> list[SalesVertical]:
        return [v for v in self.list_all() if v.activo]

    def get(self, slug: str) -> SalesVertical | None:
        slug = (slug or "").strip()
        if not slug:
            return None
        with self._store.connect() as conn:
            row = conn.execute("SELECT * FROM sales_verticals WHERE slug = ?", (slug,)).fetchone()
        return SalesVertical.from_row(row) if row else None

    def get_fallback(self) -> SalesVertical:
        vertical = self.get(FALLBACK_SLUG)
        if vertical is None:  # pragma: no cover - solo si se borro la seed a mano en BBDD
            raise VerticalNotFoundError(f"Falta la vertical fallback '{FALLBACK_SLUG}' en BBDD")
        return vertical

    def resolve(self, raw_vertical: str = "", *, fallback_text: str = "") -> SalesVertical:
        """Resuelve lenguaje natural / un slug crudo contra nombre+aliases de las
        verticales ACTIVAS. Nunca inventa una vertical nueva: si nada encaja,
        devuelve la fallback (custom).
        """
        active = self.list_active()
        by_slug = {v.slug: v for v in active}

        candidate = normalize_slug(raw_vertical)
        if candidate in by_slug:
            return by_slug[candidate]
        matched = self._match_hints(candidate, active)
        if matched:
            return matched

        if fallback_text:
            text_slug = normalize_slug(fallback_text)
            if text_slug in by_slug:
                return by_slug[text_slug]
            matched = self._match_hints(text_slug, active)
            if matched:
                return matched
            # normalize_slug() se queda solo con los primeros 3 tokens tras
            # quitar stopwords — en frases largas la palabra clave puede caer
            # fuera de ese recorte. Reintenta contra el texto libre completo
            # (solo acentos fuera + minusculas, sin tokenizar) para no perder
            # coincidencias como "clinicas dentales" en una frase de 10 palabras.
            matched = self._match_hints(normalize_full_text(fallback_text), active)
            if matched:
                return matched

        return by_slug.get(FALLBACK_SLUG) or self.get_fallback()

    @staticmethod
    def _match_hints(haystack: str, verticals: list[SalesVertical]) -> SalesVertical | None:
        if not haystack:
            return None
        for vertical in verticals:
            hints = [normalize_slug(vertical.nombre), *vertical.aliases]
            if any(hint and hint in haystack for hint in hints):
                return vertical
        return None

    # ── Escritura ───────────────────────────────────────────────────────────

    def create(
        self,
        *,
        slug: str,
        nombre: str,
        aliases: list[str] | None = None,
        scoring_rules: dict[str, Any] | None = None,
        discovery_config: dict[str, Any] | None = None,
        crm_tags: list[str] | None = None,
        crm_sector: str = "otros",
        activo: bool = True,
    ) -> SalesVertical:
        slug = normalize_slug(slug) or normalize_slug(nombre)
        if not slug:
            raise ValueError("slug o nombre requerido")
        nombre = (nombre or slug).strip()
        aliases = [normalize_slug(a) for a in (aliases or []) if normalize_slug(a)]
        self._assert_no_duplicates(slug=slug, aliases=aliases)
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sales_verticals(
                    slug, nombre, aliases_json, activo, is_fallback,
                    scoring_rules_json, discovery_config_json, crm_tags_json,
                    crm_sector, created_at, updated_at
                ) VALUES(?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug, nombre, json.dumps(aliases, ensure_ascii=False), 1 if activo else 0,
                    json.dumps(scoring_rules or {}, ensure_ascii=False),
                    json.dumps(discovery_config or {}, ensure_ascii=False),
                    json.dumps(crm_tags or [], ensure_ascii=False),
                    crm_sector or "otros", now, now,
                ),
            )
        return self.get(slug)  # type: ignore[return-value]

    def update(
        self,
        slug: str,
        *,
        nombre: str | None = None,
        aliases: list[str] | None = None,
        scoring_rules: dict[str, Any] | None = None,
        discovery_config: dict[str, Any] | None = None,
        crm_tags: list[str] | None = None,
        crm_sector: str | None = None,
    ) -> SalesVertical:
        existing = self.get(slug)
        if existing is None:
            raise VerticalNotFoundError(f"No existe la vertical '{slug}'")
        new_aliases = existing.aliases if aliases is None else [normalize_slug(a) for a in aliases if normalize_slug(a)]
        if aliases is not None:
            self._assert_no_duplicates(slug=slug, aliases=new_aliases, exclude_slug=slug)
        now = _now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                """
                UPDATE sales_verticals SET
                    nombre = ?, aliases_json = ?, scoring_rules_json = ?,
                    discovery_config_json = ?, crm_tags_json = ?, crm_sector = ?,
                    updated_at = ?
                WHERE slug = ?
                """,
                (
                    (nombre or existing.nombre).strip(),
                    json.dumps(new_aliases, ensure_ascii=False),
                    json.dumps(existing.scoring_rules if scoring_rules is None else scoring_rules, ensure_ascii=False),
                    json.dumps(existing.discovery_config if discovery_config is None else discovery_config, ensure_ascii=False),
                    json.dumps(existing.crm_tags if crm_tags is None else crm_tags, ensure_ascii=False),
                    existing.crm_sector if crm_sector is None else (crm_sector or "otros"),
                    now, slug,
                ),
            )
        return self.get(slug)  # type: ignore[return-value]

    def set_active(self, slug: str, activo: bool) -> SalesVertical:
        existing = self.get(slug)
        if existing is None:
            raise VerticalNotFoundError(f"No existe la vertical '{slug}'")
        if existing.is_fallback and not activo:
            raise ProtectedVerticalError("La vertical fallback (custom) no se puede desactivar")
        with self._store.transaction() as conn:
            conn.execute(
                "UPDATE sales_verticals SET activo = ?, updated_at = ? WHERE slug = ?",
                (1 if activo else 0, _now_iso(), slug),
            )
        return self.get(slug)  # type: ignore[return-value]

    def delete(self, slug: str) -> None:
        existing = self.get(slug)
        if existing is None:
            raise VerticalNotFoundError(f"No existe la vertical '{slug}'")
        if existing.is_fallback or existing.slug == FALLBACK_SLUG:
            raise ProtectedVerticalError("La vertical fallback (custom) no se puede eliminar")
        with self._store.transaction() as conn:
            conn.execute("DELETE FROM sales_verticals WHERE slug = ?", (slug,))

    def _assert_no_duplicates(self, *, slug: str, aliases: list[str], exclude_slug: str | None = None) -> None:
        for vertical in self.list_all():
            if exclude_slug and vertical.slug == exclude_slug:
                continue
            if vertical.slug == slug:
                raise DuplicateVerticalError(f"Ya existe una vertical con slug '{slug}'")
            overlap = set(aliases) & set(vertical.aliases)
            if overlap:
                raise DuplicateVerticalError(f"Alias ya en uso por '{vertical.slug}': {', '.join(sorted(overlap))}")
