"""Core models for local-first prospecting."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    min_employees: int | None = None
    max_employees: int | None = None
    industrial_zone: str = ""
    max_run_minutes: int = 10

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
            "min_employees": self.min_employees,
            "max_employees": self.max_employees,
            "industrial_zone": self.industrial_zone,
            "max_run_minutes": self.max_run_minutes,
        }
