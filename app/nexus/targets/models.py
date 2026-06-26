"""Shared models for technology targeting and access selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class AccessProfile:
    """How Nexus is expected to access a target technology family."""

    key: str
    connector: str
    auth_modes: list[str]
    observation_capabilities: list[str]
    action_capabilities: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class TechnologyProfile:
    """Canonical description of a supported target technology family."""

    key: str
    title: str
    family: str
    vendor: str
    summary: str
    access: AccessProfile
    default_target_kind: str
    classification_hints: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["access"] = self.access.to_dict()
        return payload
