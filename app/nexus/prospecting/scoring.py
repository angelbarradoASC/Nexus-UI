"""Data-driven scoring for prospecting results.

Los pesos por vertical ya no viven en Python — vienen de `point_criteria`
dentro de `sales_verticals.scoring_rules` (ver `sales_verticals.py`). Antes
había un método `_score_*` por vertical con un `if/elif` sobre el nombre;
cualquier vertical no reconocida (incluida `custom`) caía silenciosamente en
los criterios de "administración pública". `_score_generic` reemplaza los 5
métodos por uno solo, parametrizado por el dict de criterios de la vertical
ya resuelta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Fallback si una vertical no tiene point_criteria en absoluto (no debería
# pasar tras el backfill de sales_verticals, pero evita reventar si alguien
# construye una SalesVertical a mano sin ese campo).
_DEFAULT_POINT_CRITERIA: dict[str, Any] = {
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
    """Score prospects por vertical, usando point_criteria cargado de BBDD."""

    def score(self, result: dict[str, Any], *, vertical: Any, minimum_score: int = 20) -> dict[str, Any]:
        """`vertical` acepta un `SalesVertical` (o cualquier objeto/dict con
        `.scoring_rules`/`["scoring_rules"]`), o directamente el dict de
        `point_criteria` — nunca un string de vertical: la resolución contra
        BBDD ya la hizo el llamador (ver `ProspectingAgentService`)."""
        criteria = self._resolve_criteria(vertical)
        c = self._score_generic(result, criteria)

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

    @staticmethod
    def _resolve_criteria(vertical: Any) -> dict[str, Any]:
        """Acepta: un SalesVertical (`.scoring_rules["point_criteria"]`), un
        dict `{"point_criteria": {...}}` o `{"scoring_rules": {...}}`, o
        directamente un dict de point_criteria en crudo (para tests)."""
        if hasattr(vertical, "scoring_rules"):
            rules = vertical.scoring_rules or {}
            return rules.get("point_criteria") or _DEFAULT_POINT_CRITERIA
        if isinstance(vertical, dict):
            if "point_criteria" in vertical:
                return vertical["point_criteria"] or _DEFAULT_POINT_CRITERIA
            if "scoring_rules" in vertical:
                return (vertical["scoring_rules"] or {}).get("point_criteria") or _DEFAULT_POINT_CRITERIA
            return vertical  # ya es un point_criteria en crudo
        return _DEFAULT_POINT_CRITERIA

    def _score_generic(self, r: dict[str, Any], criteria: dict[str, Any]) -> _Criteria:
        c = _Criteria()

        c.add("Tiene web", criteria["has_website"], bool(r.get("website")))
        if criteria.get("official_website"):
            c.add("Web oficial", criteria["official_website"], bool(r.get("official_website")))
        if criteria.get("dns_valid"):
            c.add("DNS válido", criteria["dns_valid"], bool(r.get("dns_valid")))
        if criteria.get("mx_valid"):
            c.add("MX válido (email OK)", criteria["mx_valid"], bool(r.get("mx_valid")))

        if criteria.get("email_points"):
            if criteria.get("email_requires_direct"):
                c.add("Email directo", criteria["email_points"], bool(r.get("email")))
            else:
                c.add("Email o formulario", criteria["email_points"], bool(r.get("email") or r.get("contact_form_only")))
        if criteria.get("phone"):
            c.add("Teléfono", criteria["phone"], bool(r.get("phone")))
        if criteria.get("contact_form_only_bonus"):
            c.add("Formulario propio", criteria["contact_form_only_bonus"], bool(r.get("contact_form_only")))

        if criteria.get("contact_role_keywords"):
            role = r.get("contact_role", "")
            c.add(
                "Rol TIC/Digital", criteria["contact_role_keywords"],
                bool(role and any(t in role.lower() for t in ("tecnolog", "digital", "informat", "moderniz", "secretar"))),
            )
        if criteria.get("contact_person"):
            c.add("Persona de contacto", criteria["contact_person"], bool(r.get("contact_person")))

        if criteria.get("rating_high_points") or criteria.get("rating_mid_points"):
            rating = r.get("rating")
            rating_f = float(rating) if rating else 0.0
            high_t = criteria.get("rating_high_threshold", 4.0)
            mid_t = criteria.get("rating_mid_threshold", 3.5)
            if criteria.get("rating_high_points"):
                c.add(f"Valoración Google ≥ {high_t}", criteria["rating_high_points"], rating_f >= high_t)
            if criteria.get("rating_mid_points"):
                c.add(f"Valoración Google ≥ {mid_t}", criteria["rating_mid_points"], mid_t <= rating_f < high_t)

        if criteria.get("social_links_max"):
            social = len(r.get("social_links", []))
            points = min(social * criteria.get("social_links_per_item", 0), criteria["social_links_max"])
            c.add(f"Redes sociales ({social})", points, social > 0)

        if criteria.get("quality_signals_max"):
            signals = len(r.get("quality_signals", []))
            points = min(signals * criteria.get("quality_signals_per_item", 0), criteria["quality_signals_max"])
            c.add(f"Señales de calidad ({signals})", points, signals > 0)

        if criteria.get("premium_bonus"):
            c.add("Premium", criteria["premium_bonus"], bool(r.get("is_premium")))

        if criteria.get("contact_form_only_penalty"):
            c.penalty(
                "Solo formulario de contacto", criteria["contact_form_only_penalty"],
                bool(r.get("contact_form_only") and not r.get("email")),
            )
        if criteria.get("crm_duplicate_penalty"):
            c.penalty("Duplicado en CRM", criteria["crm_duplicate_penalty"], bool(r.get("crm_duplicate")))

        return c
