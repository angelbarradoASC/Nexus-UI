"""Vertical-aware scoring for prospecting results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Criteria:
    """Accumulates score + breakdown during evaluation."""
    items: list[dict] = field(default_factory=list)
    total: int = 0

    def add(self, label: str, points: int, earned: bool) -> None:
        actual = points if earned else 0
        self.items.append({"label": label, "points": points, "earned": earned, "actual": actual})
        self.total += actual

    def penalty(self, label: str, points: int, applies: bool) -> None:
        actual = -abs(points) if applies else 0
        self.items.append({"label": label, "points": -abs(points), "earned": applies, "actual": actual})
        self.total += actual


@dataclass(slots=True)
class ProspectScorer:
    """Score prospects by vertical, returning score + per-criterion breakdown."""

    def score(self, result: dict[str, Any], *, vertical: str, minimum_score: int = 20) -> dict[str, Any]:
        if vertical == "restaurants":
            c = self._score_restaurant(result)
        elif vertical == "asesoria":
            c = self._score_asesoria(result)
        elif vertical == "inmobiliaria":
            c = self._score_inmobiliaria(result)
        elif vertical == "salud":
            c = self._score_salud(result)
        else:
            c = self._score_public_administration(result)

        score = max(0, min(100, c.total))
        if score >= 80:
            priority = "Alta"
        elif score >= 50:
            priority = "Media"
        elif score >= 20:
            priority = "Baja"
        else:
            priority = "Descartar"

        return {
            "score": score,
            "priority": priority,
            "accepted": score >= minimum_score,
            "discard_reason": None if score >= minimum_score else "score_below_threshold",
            "score_breakdown": c.items,
        }

    def _score_public_administration(self, r: dict[str, Any]) -> _Criteria:
        c = _Criteria()
        c.add("Tiene web",            20, bool(r.get("website")))
        c.add("Web oficial",          10, bool(r.get("official_website")))
        c.add("DNS válido",           10, bool(r.get("dns_valid")))
        c.add("MX válido (email OK)", 15, bool(r.get("mx_valid")))
        c.add("Email directo",        15, bool(r.get("email")))
        c.add("Teléfono",             10, bool(r.get("phone")))
        role = r.get("contact_role", "")
        c.add("Rol TIC/Digital",      10, bool(role and any(t in role.lower() for t in ("tecnolog","digital","informat","moderniz","secretar"))))
        c.add("Persona de contacto",   5, bool(r.get("contact_person")))
        signals = len(r.get("quality_signals", []))
        c.add(f"Señales de calidad ({signals})", min(signals * 5, 15), signals > 0)
        c.penalty("Solo formulario de contacto", 10, bool(r.get("contact_form_only") and not r.get("email")))
        c.penalty("Duplicado en CRM",            25, bool(r.get("crm_duplicate")))
        return c

    def _score_asesoria(self, r: dict[str, Any]) -> _Criteria:
        c = _Criteria()
        c.add("Tiene web",            20, bool(r.get("website")))
        c.add("DNS válido",           10, bool(r.get("dns_valid")))
        c.add("MX válido (email OK)", 15, bool(r.get("mx_valid")))
        c.add("Email directo",        15, bool(r.get("email")))
        c.add("Teléfono",             15, bool(r.get("phone")))
        c.add("Persona de contacto",   5, bool(r.get("contact_person")))
        rating = r.get("rating")
        rating_f = float(rating) if rating else 0.0
        c.add("Valoración Google ≥ 4.0", 10, rating_f >= 4.0)
        c.add("Valoración Google ≥ 3.5",  5, 3.5 <= rating_f < 4.0)
        signals = len(r.get("quality_signals", []))
        c.add(f"Señales de calidad ({signals})", min(signals * 5, 10), signals > 0)
        c.penalty("Solo formulario de contacto", 10, bool(r.get("contact_form_only") and not r.get("email")))
        c.penalty("Duplicado en CRM",            25, bool(r.get("crm_duplicate")))
        return c

    def _score_inmobiliaria(self, r: dict[str, Any]) -> _Criteria:
        c = _Criteria()
        c.add("Tiene web",            20, bool(r.get("website")))
        c.add("DNS válido",           10, bool(r.get("dns_valid")))
        c.add("MX válido (email OK)", 10, bool(r.get("mx_valid")))
        c.add("Email o formulario",   15, bool(r.get("email") or r.get("contact_form_only")))
        c.add("Teléfono",             15, bool(r.get("phone")))
        rating = r.get("rating")
        rating_f = float(rating) if rating else 0.0
        c.add("Valoración Google ≥ 4.0", 10, rating_f >= 4.0)
        c.add("Valoración Google ≥ 3.5",  5, 3.5 <= rating_f < 4.0)
        social = len(r.get("social_links", []))
        c.add(f"Redes sociales ({social})", min(social * 4, 12), social > 0)
        signals = len(r.get("quality_signals", []))
        c.add(f"Señales de calidad ({signals})", min(signals * 5, 10), signals > 0)
        c.penalty("Duplicado en CRM", 25, bool(r.get("crm_duplicate")))
        return c

    def _score_salud(self, r: dict[str, Any]) -> _Criteria:
        c = _Criteria()
        c.add("Tiene web",            20, bool(r.get("website")))
        c.add("DNS válido",           10, bool(r.get("dns_valid")))
        c.add("MX válido (email OK)", 10, bool(r.get("mx_valid")))
        c.add("Email o formulario",   15, bool(r.get("email") or r.get("contact_form_only")))
        c.add("Teléfono",             15, bool(r.get("phone")))
        rating = r.get("rating")
        rating_f = float(rating) if rating else 0.0
        c.add("Valoración Google ≥ 4.0", 10, rating_f >= 4.0)
        c.add("Valoración Google ≥ 3.5",  5, 3.5 <= rating_f < 4.0)
        social = len(r.get("social_links", []))
        c.add(f"Redes sociales ({social})", min(social * 4, 12), social > 0)
        signals = len(r.get("quality_signals", []))
        c.add(f"Señales de calidad ({signals})", min(signals * 5, 10), signals > 0)
        c.penalty("Duplicado en CRM", 25, bool(r.get("crm_duplicate")))
        return c

    def _score_restaurant(self, r: dict[str, Any]) -> _Criteria:
        c = _Criteria()
        c.add("Tiene web",            15, bool(r.get("website")))
        c.add("DNS válido",           10, bool(r.get("dns_valid")))
        c.add("MX válido (email OK)", 10, bool(r.get("mx_valid")))
        c.add("Email o formulario",   15, bool(r.get("email") or r.get("contact_form_only")))
        c.add("Teléfono",             10, bool(r.get("phone")))
        c.add("Formulario propio",     5, bool(r.get("contact_form_only")))
        social = len(r.get("social_links", []))
        c.add(f"Redes sociales ({social})", min(social * 4, 12), social > 0)
        signals = len(r.get("quality_signals", []))
        c.add(f"Señales de calidad ({signals})", min(signals * 6, 24), signals > 0)
        c.add("Premium",               8, bool(r.get("is_premium")))
        c.penalty("Duplicado en CRM", 25, bool(r.get("crm_duplicate")))
        return c
