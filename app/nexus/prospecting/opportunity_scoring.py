"""Vertical-agnostic opportunity scoring for campaign outreach.

Distinto del ProspectScorer de scoring.py (que mide calidad de datos del
candidato: tiene web, email valido, telefono...). Este mide si vale la pena
gastar uno de los contactos diarios (escasos, deliberadamente) en esta
empresa: cuantos problemas reales se han encontrado, si la propuesta esta
bien fundamentada, y la madurez digital detectada. No tiene branches por
vertical — funciona igual para cualquier sector, coherente con que la
vertical ya es 100% configurable en BBDD (sales_verticals) y no debe
hardcodearse aqui tampoco.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MATURITY_POINTS = {"bajo": 25, "medio": 12, "alto": 0}


@dataclass(slots=True)
class OpportunityScorer:
    """Score de oportunidad comercial (0-100), independiente del vertical."""

    def score(
        self,
        *,
        data_quality_score: int,
        technical_audit: dict[str, Any] | None,
        business_profile: dict[str, Any] | None,
        proposal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        breakdown: list[dict[str, Any]] = []

        # La calidad de datos ya calculada por ProspectScorer cuenta como una
        # señal proporcional mas, no como el score entero — un lead con email
        # y telefono perfectos pero sin ningun problema real detectado no es
        # una buena oportunidad de contacto.
        data_quality_points = round(20 * max(0, min(100, data_quality_score)) / 100)
        breakdown.append({"label": "Calidad de datos del lead", "max_points": 20, "actual": data_quality_points})

        findings = (technical_audit or {}).get("findings") or []
        severity_points = min(len(findings) * 8, 30)
        breakdown.append({
            "label": f"Problemas tecnicos detectados ({len(findings)})",
            "max_points": 30,
            "actual": severity_points,
        })

        maturity = str((business_profile or {}).get("digital_maturity") or "").lower()
        maturity_points = _MATURITY_POINTS.get(maturity, 0)
        breakdown.append({
            "label": "Madurez digital baja/media (mas margen de mejora)",
            "max_points": 25,
            "actual": maturity_points,
        })

        proposal_items = (proposal or {}).get("items") or []
        grounded_items = [item for item in proposal_items if item.get("grounded")]
        proposal_points = min(len(grounded_items) * 10, 25)
        breakdown.append({
            "label": f"Propuestas concretas y fundamentadas ({len(grounded_items)})",
            "max_points": 25,
            "actual": proposal_points,
        })

        score = max(0, min(100, sum(item["actual"] for item in breakdown)))
        if score >= 70:
            confidence = "alta"
        elif score >= 40:
            confidence = "media"
        else:
            confidence = "baja"

        return {
            "opportunity_score": score,
            "opportunity_confidence": confidence,
            "opportunity_breakdown": breakdown,
        }
