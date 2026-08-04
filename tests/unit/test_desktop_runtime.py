from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desktop.config import DesktopSettings
from desktop.local_agents.monitoring_agent import MonitoringAgent
from desktop.runtime.assistant_runtime import DesktopAssistantRuntime
from desktop.runtime.capabilities import PermissionLevel
from desktop.runtime.skill_router import DesktopSkillRouter
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


def test_desktop_settings_from_env_lee_overrides():
    with patch.dict(
        "os.environ",
        {
            "APP_PORT": "12000",
            "NEXUS_CONTEXT": "desktop_app",
            "DESKTOP_HOST": "127.0.0.2",
            "DESKTOP_STARTUP_TIMEOUT": "25",
            "DESKTOP_MONITOR_INTERVAL": "45",
            "DESKTOP_INTERNAL_TOKEN": "token-123",
            "DESKTOP_STARTUP_ROUTE": "/open-nexus",
            "DESKTOP_OPEN_OPERATOR_ON_START": "true",
            "DEBUG": "true",
            "OPEN_NEXUS_DATA_DIR": "C:\\temp\\open-nexus-test",
        },
        clear=False,
    ):
        settings = DesktopSettings.from_env()

    assert settings.app_port == 12000
    assert settings.host == "127.0.0.2"
    assert settings.startup_timeout_seconds == 25
    assert settings.monitoring_interval_seconds == 45
    assert settings.desktop_internal_token == "token-123"
    assert settings.debug is True
    assert settings.local_url == "http://127.0.0.2:12000"
    assert settings.startup_url == "http://127.0.0.2:12000/open-nexus"
    assert settings.open_operator_on_start is True
    assert settings.resolved_local_data_root == Path("C:/temp/open-nexus-test").resolve()


def test_monitoring_agent_push_metrics_usa_token_si_existe():
    agent = MonitoringAgent(
        interval_seconds=30,
        local_url="http://127.0.0.1:11430",
        internal_token="desktop-token",
    )

    with patch("desktop.local_agents.monitoring_agent.httpx.post") as post:
        agent._push_metrics({"cpu": {"percent": 10}}, [])

    _, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer desktop-token"


def test_monitoring_agent_push_metrics_sin_token_no_envia_auth():
    agent = MonitoringAgent(
        interval_seconds=30,
        local_url="http://127.0.0.1:11430",
        internal_token="",
    )

    with patch("desktop.local_agents.monitoring_agent.httpx.post") as post:
        agent._push_metrics({"cpu": {"percent": 10}}, [])

    _, kwargs = post.call_args
    assert kwargs["headers"] == {}


def test_desktop_runtime_expone_capacidades_y_permiso_filtrado():
    runtime = DesktopAssistantRuntime(DesktopSettings())

    description = runtime.describe()
    allowed = runtime.allowed_capabilities(PermissionLevel.ASSIST)

    assert description["surface"] == "desktop"
    assert description["permissions"]["total"] >= 5
    assert any(item["key"] == "desktop.metrics.read" for item in description["capabilities"])
    assert any(item["key"] == "infra.linux.observe" for item in description["capabilities"])
    assert any(item["key"] == "infra.windows.observe" for item in description["capabilities"])
    assert any(item["key"] == "infra.fortinet.observe" for item in description["capabilities"])
    assert any(item["key"] == "infra.cisco.observe" for item in description["capabilities"])
    assert all(item["permission_level"] <= int(PermissionLevel.ASSIST) for item in allowed)


def test_skill_router_detecta_diagnostico_operativo():
    router = DesktopSkillRouter()

    resolution = router.resolve("diagnostica el servidor web-prod-01 que va lento")

    assert resolution.skill_id == "ssh.diagnostico"
    assert resolution.entities["servidor"] == "web-prod-01"
    assert resolution.permission_level == int(PermissionLevel.OPERATE)
    assert resolution.needs_confirmation is True


def test_skill_router_detecta_prediagnostico_docker():
    router = DesktopSkillRouter()

    resolution = router.resolve("tengo una alarma de docker en el contenedor api-worker")

    assert resolution.skill_id == "docker.prediagnostico"
    assert resolution.entities["container"] == "api-worker"
    assert resolution.permission_level == int(PermissionLevel.ASSIST)
    assert "desktop.docker.inspect" in resolution.required_capabilities


def test_skill_router_detecta_prediagnostico_linux():
    router = DesktopSkillRouter()

    resolution = router.resolve("tengo una alarma en el servidor linux web-prod-01")

    assert resolution.skill_id == "linux.prediagnostico"
    assert resolution.entities["servidor"] == "web-prod-01"
    assert "infra.linux.observe" in resolution.required_capabilities


def test_skill_router_detecta_prediagnostico_windows():
    router = DesktopSkillRouter()

    resolution = router.resolve("revisa el windows server app-win-02 por powershell")

    assert resolution.skill_id == "windows.prediagnostico"
    assert resolution.entities["servidor"] == "app-win-02"
    assert "infra.windows.observe" in resolution.required_capabilities


def test_desktop_runtime_resuelve_y_actualiza_sesion():
    runtime = DesktopAssistantRuntime(DesktopSettings())

    result = runtime.resolve_user_input("consulta el ticket NEXUS-42")

    assert result["skill_id"] == "jira.consultar_ticket"
    assert result["entities"]["ticket_id"] == "NEXUS-42"
    assert runtime.session.active_skill == "jira.consultar_ticket"


def test_desktop_local_state_crea_layout(tmp_path):
    settings = DesktopSettings(local_data_root=str(tmp_path))
    state = DesktopLocalState(settings)

    state.ensure_layout()

    assert state.config_dir.exists()
    assert state.logs_dir.exists()
    assert state.history_dir.exists()


def test_desktop_local_state_guarda_llm_provider_config(tmp_path):
    settings = DesktopSettings(local_data_root=str(tmp_path))
    state = DesktopLocalState(
        settings,
        provider_secret_store=DesktopProviderSecretStore(_FakeSecretBackend()),
    )

    saved = state.save_llm_provider_config(
        DesktopLLMProviderConfig(
            provider_label="Claude remoto",
            api_base_url="https://llm.example.com/v1",
            api_key="secret-1234",
            model="claude-sonnet-4",
            enabled=True,
        )
    )
    loaded = state.load_llm_provider_config()

    assert saved.updated_at
    assert state.llm_provider_config_path.exists()
    assert loaded.provider_label == "Claude remoto"
    assert loaded.api_base_url == "https://llm.example.com/v1"
    assert loaded.model == "claude-sonnet-4"
    assert loaded.enabled is True
    assert loaded.api_key == "secret-1234"
