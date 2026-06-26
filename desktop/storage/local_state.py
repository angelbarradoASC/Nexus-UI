"""Local persistence for Open-Nexus desktop state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from nexus.security.desktop_secret_store import (
    DesktopProviderSecretStore,
    build_desktop_provider_secret_store,
)
from desktop.config import DesktopSettings
from desktop.storage.atomic_io import atomic_write_text
from desktop.storage.provider_config import DesktopLLMProviderConfig

if TYPE_CHECKING:
    from desktop.opennexus.models import OpenNexusResult


class DesktopLocalState:
    """Persists minimal desktop runtime state under LOCALAPPDATA."""

    def __init__(
        self,
        settings: DesktopSettings,
        provider_secret_store: DesktopProviderSecretStore | None = None,
    ) -> None:
        self.settings = settings
        self.root = settings.resolved_local_data_root
        self.config_dir = settings.config_dir
        self.logs_dir = settings.logs_dir
        self.history_dir = settings.history_dir
        self.shell_history_path = settings.shell_history_path
        self.llm_provider_config_path = settings.llm_provider_config_path
        self._provider_secret_store = provider_secret_store

    def ensure_layout(self) -> None:
        for path in (self.root, self.config_dir, self.logs_dir, self.history_dir):
            path.mkdir(parents=True, exist_ok=True)

    def load_shell_history(self, *, limit: int = 40) -> list[OpenNexusResult]:
        self.ensure_layout()
        if not self.shell_history_path.exists():
            return []

        from desktop.opennexus.models import OpenNexusResult

        items: list[OpenNexusResult] = []
        lines = self.shell_history_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            if not line.strip():
                continue
            payload = json.loads(line)
            items.append(OpenNexusResult(**payload))
        items.reverse()
        return items

    def append_shell_history(self, result: OpenNexusResult) -> None:
        self.ensure_layout()
        existing = ""
        if self.shell_history_path.exists():
            existing = self.shell_history_path.read_text(encoding="utf-8")
        line = json.dumps(result.to_dict(), ensure_ascii=False) + "\n"
        atomic_write_text(self.shell_history_path, existing + line, encoding="utf-8")

    def rewrite_shell_history(self, items: Iterable[OpenNexusResult]) -> None:
        self.ensure_layout()
        lines = [json.dumps(item.to_dict(), ensure_ascii=False) for item in items]
        content = ("\n".join(lines) + "\n") if lines else ""
        atomic_write_text(self.shell_history_path, content, encoding="utf-8")

    def load_llm_provider_config(self) -> DesktopLLMProviderConfig:
        self.ensure_layout()
        if not self.llm_provider_config_path.exists():
            return DesktopLLMProviderConfig()

        payload = json.loads(self.llm_provider_config_path.read_text(encoding="utf-8"))
        provider_config = DesktopLLMProviderConfig.from_dict(payload)
        legacy_api_key = str(payload.get("api_key", "") or "").strip()
        if legacy_api_key and not provider_config.credential_ref:
            provider_config = self._migrate_legacy_provider_secret(provider_config, legacy_api_key)
        elif provider_config.credential_ref:
            provider_config = DesktopLLMProviderConfig.from_dict(
                {
                    **provider_config.to_dict(include_secret=False),
                    "api_key": self._get_provider_secret_store().load(provider_config.credential_ref),
                }
            )
        return provider_config

    def save_llm_provider_config(self, provider_config: DesktopLLMProviderConfig) -> DesktopLLMProviderConfig:
        self.ensure_layout()
        provider_config = provider_config.touched()
        if provider_config.api_key:
            credential_ref = provider_config.credential_ref or self._default_provider_credential_ref(provider_config)
            self._get_provider_secret_store().save(credential_ref, provider_config.api_key)
            provider_config = DesktopLLMProviderConfig.from_dict(
                {
                    **provider_config.to_dict(include_secret=False),
                    "api_key": provider_config.api_key,
                    "credential_ref": credential_ref,
                }
            )
        atomic_write_text(
            self.llm_provider_config_path,
            json.dumps(provider_config.to_dict(include_secret=False), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return provider_config

    def _migrate_legacy_provider_secret(
        self,
        provider_config: DesktopLLMProviderConfig,
        legacy_api_key: str,
    ) -> DesktopLLMProviderConfig:
        migrated = DesktopLLMProviderConfig.from_dict(
            {
                **provider_config.to_dict(include_secret=False),
                "api_key": legacy_api_key,
                "credential_ref": provider_config.credential_ref or self._default_provider_credential_ref(provider_config),
            }
        ).touched()
        self._get_provider_secret_store().save(migrated.credential_ref, legacy_api_key)
        self._backup_legacy_provider_file_once()
        atomic_write_text(
            self.llm_provider_config_path,
            json.dumps(migrated.to_dict(include_secret=False), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return migrated

    def _get_provider_secret_store(self) -> DesktopProviderSecretStore:
        if self._provider_secret_store is None:
            self._provider_secret_store = build_desktop_provider_secret_store()
        return self._provider_secret_store

    def _backup_legacy_provider_file_once(self) -> None:
        pattern = f"{self.llm_provider_config_path.stem}.pre-secrets-migration-*.json"
        if any(self.llm_provider_config_path.parent.glob(pattern)):
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.llm_provider_config_path.with_name(
            f"{self.llm_provider_config_path.stem}.pre-secrets-migration-{timestamp}.json"
        )
        atomic_write_text(
            backup_path,
            self.llm_provider_config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    @staticmethod
    def _default_provider_credential_ref(provider_config: DesktopLLMProviderConfig) -> str:
        provider_type = str(provider_config.provider_type or "provider").strip().lower().replace(" ", "_")
        return f"nexus.desktop.provider.{provider_type}.primary"
