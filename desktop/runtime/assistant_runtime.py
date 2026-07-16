"""Local assistant runtime for Nexus Desktop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from desktop.config import DesktopSettings
from desktop.runtime.capabilities import CapabilityRegistry, PermissionLevel, build_default_registry
from desktop.runtime.skill_router import DesktopSkillRouter
from desktop.runtime.skills import DesktopSkillCatalogue


@dataclass(slots=True)
class DesktopSessionState:
    """Minimal local session state for the assistant runtime."""

    mode: str = "general_assistant"
    active_skill: str | None = None
    last_user_intent: str | None = None
    last_updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def touch(self, *, intent: str | None = None, skill: str | None = None) -> None:
        if intent is not None:
            self.last_user_intent = intent
        if skill is not None:
            self.active_skill = skill
        self.last_updated_at = datetime.now(timezone.utc).isoformat()


class DesktopAssistantRuntime:
    """Shared desktop runtime state exposed to the embedded app and local shell."""

    def __init__(
        self,
        settings: DesktopSettings,
        *,
        capabilities: CapabilityRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.capabilities = capabilities or build_default_registry()
        self.skills = DesktopSkillCatalogue()
        self.skill_router = DesktopSkillRouter(self.skills)
        self.session = DesktopSessionState()
        self.local_agents: list[str] = [
            "monitoring_agent",
            "hardware_agent",
        ]

    def record_intent(self, intent: str, skill: str | None = None) -> None:
        self.session.touch(intent=intent, skill=skill)

    def resolve_user_input(self, user_input: str) -> dict:
        resolution = self.skill_router.resolve(user_input)
        self.record_intent(user_input, skill=resolution.skill_id)
        return resolution.to_dict()

    def allowed_capabilities(
        self,
        level: PermissionLevel = PermissionLevel.ASSIST,
    ) -> list[dict]:
        return [
            capability.to_dict()
            for capability in self.capabilities.list_by_permission(level)
        ]

    def describe(self) -> dict:
        return {
            "surface": "desktop",
            "mode": self.session.mode,
            "local_url": self.settings.local_url,
            "context": self.settings.nexus_context,
            "local_agents": self.local_agents,
            "session": {
                "active_skill": self.session.active_skill,
                "last_user_intent": self.session.last_user_intent,
                "last_updated_at": self.session.last_updated_at,
            },
            "permissions": self.capabilities.summary(),
            "skills": {
                "total": len(self.skills.ids()),
                "ids": self.skills.ids(),
                "catalogue": [skill.to_dict() for skill in self.skills.all()],
            },
            "capabilities": [
                capability.to_dict() for capability in self.capabilities.list_all()
            ],
            "examples": [
                example
                for skill in self.skills.all()
                for example in skill.examples[:1]
            ][:8],
        }
