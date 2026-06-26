"""Persistent remote LLM provider configuration for Open-Nexus desktop."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class DesktopLLMProviderConfig:
    """Remote model endpoint configuration stored in LOCALAPPDATA."""

    provider_type: str = "openai_compatible"
    provider_label: str = "Servidor remoto"
    api_base_url: str = ""
    api_key: str = ""
    credential_ref: str = ""
    model: str = ""
    enabled: bool = False
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict | None) -> "DesktopLLMProviderConfig":
        payload = payload or {}
        return cls(
            provider_type=str(payload.get("provider_type", "openai_compatible") or "openai_compatible"),
            provider_label=str(payload.get("provider_label", "Servidor remoto") or "Servidor remoto"),
            api_base_url=str(payload.get("api_base_url", "") or "").strip(),
            api_key=str(payload.get("api_key", "") or "").strip(),
            credential_ref=str(payload.get("credential_ref", "") or "").strip(),
            model=str(payload.get("model", "") or "").strip(),
            enabled=bool(payload.get("enabled", False)),
            updated_at=str(payload.get("updated_at", "") or ""),
        )

    def to_dict(self, *, mask_secret: bool = False, include_secret: bool = True) -> dict:
        payload = asdict(self)
        if not include_secret:
            payload["api_key"] = ""
        if mask_secret and payload["api_key"]:
            payload["api_key"] = self.masked_api_key
        return payload

    @property
    def masked_api_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}{'*' * max(len(self.api_key) - 8, 4)}{self.api_key[-4:]}"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base_url and self.model)

    def touched(self) -> "DesktopLLMProviderConfig":
        return DesktopLLMProviderConfig(
            provider_type=self.provider_type,
            provider_label=self.provider_label,
            api_base_url=self.api_base_url,
            api_key=self.api_key,
            credential_ref=self.credential_ref,
            model=self.model,
            enabled=self.enabled,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
