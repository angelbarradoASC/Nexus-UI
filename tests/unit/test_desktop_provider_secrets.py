from __future__ import annotations

import json

import pytest

from desktop.config import DesktopSettings
from desktop.storage.local_state import DesktopLocalState
from desktop.storage.provider_config import DesktopLLMProviderConfig
from nexus.security.desktop_secret_store import (
    DesktopProviderSecretStore,
    DesktopSecretStoreError,
)


class _FakeBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


class _BrokenBackend:
    def get_password(self, service_name: str, username: str) -> str | None:
        raise RuntimeError("backend get failure")

    def set_password(self, service_name: str, username: str, password: str) -> None:
        raise RuntimeError(f"backend save failure for {password}")

    def delete_password(self, service_name: str, username: str) -> None:
        raise RuntimeError("backend delete failure")


def _secret_store(backend) -> DesktopProviderSecretStore:
    return DesktopProviderSecretStore(backend=backend)


def test_provider_secret_save_moves_api_key_out_of_json(tmp_path):
    state = DesktopLocalState(
        DesktopSettings(local_data_root=str(tmp_path)),
        provider_secret_store=_secret_store(_FakeBackend()),
    )

    saved = state.save_llm_provider_config(
        DesktopLLMProviderConfig(
            provider_label="Seguro",
            api_base_url="https://secure.example/v1",
            api_key="sk-super-secret-1234",
            model="secure-model",
            enabled=True,
        )
    )
    raw_payload = json.loads(state.llm_provider_config_path.read_text(encoding="utf-8"))
    loaded = state.load_llm_provider_config()

    assert saved.credential_ref == "nexus.desktop.provider.openai_compatible.primary"
    assert raw_payload["api_key"] == ""
    assert raw_payload["credential_ref"] == saved.credential_ref
    assert loaded.api_key == "sk-super-secret-1234"


def test_provider_secret_migrates_legacy_json_and_creates_backup(tmp_path):
    state = DesktopLocalState(
        DesktopSettings(local_data_root=str(tmp_path)),
        provider_secret_store=_secret_store(_FakeBackend()),
    )
    state.ensure_layout()
    state.llm_provider_config_path.write_text(
        json.dumps(
            {
                "provider_type": "openai_compatible",
                "provider_label": "Legacy",
                "api_base_url": "https://legacy.example/v1",
                "api_key": "legacy-secret-1234",
                "model": "legacy-model",
                "enabled": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = state.load_llm_provider_config()
    migrated_raw = json.loads(state.llm_provider_config_path.read_text(encoding="utf-8"))
    backups = list(state.config_dir.glob("llm_provider.pre-secrets-migration-*.json"))

    assert loaded.api_key == "legacy-secret-1234"
    assert migrated_raw["api_key"] == ""
    assert migrated_raw["credential_ref"] == "nexus.desktop.provider.openai_compatible.primary"
    assert len(backups) == 1
    assert "legacy-secret-1234" in backups[0].read_text(encoding="utf-8")


def test_provider_secret_backend_error_does_not_leak_secret(tmp_path):
    state = DesktopLocalState(
        DesktopSettings(local_data_root=str(tmp_path)),
        provider_secret_store=_secret_store(_BrokenBackend()),
    )

    with pytest.raises(DesktopSecretStoreError) as exc_info:
        state.save_llm_provider_config(
            DesktopLLMProviderConfig(
                provider_label="Broken",
                api_base_url="https://broken.example/v1",
                api_key="should-not-leak-9876",
                model="broken-model",
                enabled=True,
            )
        )

    message = str(exc_info.value)
    assert "should-not-leak-9876" not in message
    assert not state.llm_provider_config_path.exists()


def test_provider_json_without_secret_still_works(tmp_path):
    state = DesktopLocalState(
        DesktopSettings(local_data_root=str(tmp_path)),
        provider_secret_store=_secret_store(_FakeBackend()),
    )

    saved = state.save_llm_provider_config(
        DesktopLLMProviderConfig(
            provider_label="Public only",
            api_base_url="https://public.example/v1",
            api_key="",
            model="public-model",
            enabled=False,
        )
    )
    raw_payload = json.loads(state.llm_provider_config_path.read_text(encoding="utf-8"))
    loaded = state.load_llm_provider_config()

    assert saved.credential_ref == ""
    assert raw_payload["credential_ref"] == ""
    assert loaded.api_key == ""
