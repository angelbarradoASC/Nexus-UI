from __future__ import annotations

from desktop.config import DesktopSettings
from desktop.opennexus.models import OpenNexusResult
from desktop.storage.local_state import DesktopLocalState
from desktop.storage.provider_config import DesktopLLMProviderConfig
from nexus.security.desktop_secret_store import DesktopProviderSecretStore


class _FakeSecretBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


def test_local_state_reinicio_conserva_provider_e_historial(tmp_path):
    settings = DesktopSettings(local_data_root=str(tmp_path))
    secret_store = DesktopProviderSecretStore(_FakeSecretBackend())
    state = DesktopLocalState(settings, provider_secret_store=secret_store)

    state.save_llm_provider_config(
        DesktopLLMProviderConfig(
            provider_label="Seguro",
            api_base_url="https://audit.example/v1",
            api_key="secret-local-1234",
            model="audit-model",
            enabled=True,
        )
    )
    state.append_shell_history(
        OpenNexusResult(
            user_input="comando uno",
            resolution={"skill_id": "general.respuesta", "confidence": 0.7, "execution_mode": "assist"},
            response="ok",
            agent="audit-agent",
            status="accepted",
            created_at="2026-06-21T18:30:00+00:00",
        )
    )
    state.append_shell_history(
        OpenNexusResult(
            user_input="comando dos",
            resolution={"skill_id": "general.respuesta", "confidence": 0.8, "execution_mode": "assist"},
            response="ok",
            agent="audit-agent",
            status="accepted",
            created_at="2026-06-21T18:31:00+00:00",
        )
    )

    reloaded = DesktopLocalState(DesktopSettings(local_data_root=str(tmp_path)), provider_secret_store=secret_store)
    provider = reloaded.load_llm_provider_config()
    history = reloaded.load_shell_history(limit=10)

    assert provider.provider_label == "Seguro"
    assert provider.api_base_url == "https://audit.example/v1"
    assert provider.model == "audit-model"
    assert provider.api_key == "secret-local-1234"
    assert [item.user_input for item in history] == ["comando dos", "comando uno"]
