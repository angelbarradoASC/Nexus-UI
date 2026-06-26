"""Heuristic technology classifier for the first multi-platform Nexus targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexus.targets.catalogue import TechnologyCatalogue
from nexus.targets.models import TechnologyProfile


@dataclass(slots=True)
class TechnologyResolution:
    """Result of classifying a message or alert into a target technology family."""

    technology_key: str
    confidence: float
    rationale: str
    target_hint: str | None = None
    access_key: str | None = None
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "technology_key": self.technology_key,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale,
            "target_hint": self.target_hint,
            "access_key": self.access_key,
            "capabilities": list(self.capabilities),
            "metadata": dict(self.metadata),
        }


class TechnologyClassifier:
    """Simple but explicit classifier for the first infrastructure families."""

    def __init__(self, catalogue: TechnologyCatalogue | None = None) -> None:
        self.catalogue = catalogue or TechnologyCatalogue()

    def classify(
        self,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> TechnologyResolution | None:
        lowered = text.lower()
        metadata = metadata or {}
        labels = self._flatten_metadata(metadata)

        best_profile: TechnologyProfile | None = None
        best_score = 0
        best_hits: list[str] = []

        for profile in self.catalogue.all():
            hits = self._matching_hints(profile, lowered, labels)
            score = len(hits)
            if score > best_score:
                best_score = score
                best_profile = profile
                best_hits = hits

        if best_profile is None or best_score == 0:
            return None

        target_hint = self._extract_target_hint(text)
        capabilities = list(best_profile.access.observation_capabilities)
        rationale = f"Coincidencia con {best_profile.title} por pistas: {', '.join(best_hits[:4])}."
        confidence = min(0.52 + (best_score * 0.12), 0.96)
        return TechnologyResolution(
            technology_key=best_profile.key,
            confidence=confidence,
            rationale=rationale,
            target_hint=target_hint,
            access_key=best_profile.access.key,
            capabilities=capabilities,
            metadata={"vendor": best_profile.vendor, "family": best_profile.family},
        )

    def _matching_hints(
        self,
        profile: TechnologyProfile,
        lowered: str,
        labels: str,
    ) -> list[str]:
        hits: list[str] = []
        for hint in profile.classification_hints:
            hint_lower = hint.lower()
            if hint_lower in lowered or hint_lower in labels:
                hits.append(hint)
        return hits

    def _flatten_metadata(self, metadata: dict[str, Any]) -> str:
        chunks: list[str] = []
        for key, value in metadata.items():
            if isinstance(value, dict):
                chunks.append(key)
                chunks.extend(f"{sub_key}:{sub_value}" for sub_key, sub_value in value.items())
            else:
                chunks.append(f"{key}:{value}")
        return " ".join(str(chunk).lower() for chunk in chunks)

    def _extract_target_hint(self, text: str) -> str | None:
        tokens = [token.strip(" ,.;:()[]{}") for token in text.split()]
        for token in tokens:
            lowered = token.lower()
            if any(char.isdigit() for char in lowered) or "-" in lowered:
                return token
        return None
