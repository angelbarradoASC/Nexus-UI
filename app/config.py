"""
app/config.py
-------------
Configuracion centralizada de NEXUS-UI.

Importar siempre: from config import cfg
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRET_KEY = "change-this-secret-key"
_INSECURE_STORE_KEY = "change-this-encryption-key-32chars"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DESKTOP_LOCAL_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Open-Nexus"


def _resolve_env_files() -> tuple[str, ...]:
    candidates = (
        _DESKTOP_LOCAL_ROOT / "_internal" / ".env",
        _DESKTOP_LOCAL_ROOT / ".env",
        _REPO_ROOT / ".env",
    )
    existing = [str(path) for path in candidates if path.exists()]
    if existing:
        return tuple(existing)
    return (str(_REPO_ROOT / ".env"),)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "NEXUS-UI"
    app_version: str = "1.0.0"
    app_port: int = Field(default=5010, ge=1024, le=65535)
    debug: bool = False
    nexus_context: str = Field(default="web_app")
    app_environment: Literal["development", "production"] = "development"

    secret_key: str = Field(default=_INSECURE_SECRET_KEY)
    app_users: str = Field(default="admin:changeme")

    session_expire_hours: int = Field(default=24, ge=1, le=720)
    session_secure_cookie: bool = False

    mongo_uri: str | None = None
    mongo_db_name: str = "nexus_db"

    redis_host: str = "redis"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: str | None = None

    llm_priority: str = Field(default="cost", pattern=r"^(cost|speed|balanced)$")
    llm_api_base_url: str | None = None
    llm_api_key: str = "not-needed"
    llm_model: str = "local-model"
    llm_l0_url: str | None = None
    llm_l0_key: str = "not-needed"
    llm_l0_model: str = "local-model"
    llm_l1_url: str | None = None
    llm_l1_key: str | None = None
    llm_l1_model: str = "llama-3.3-70b-versatile"
    llm_l2_url: str | None = None
    llm_l2_key: str | None = None
    llm_l2_model: str = "gpt-4o-mini"
    llm_l3_url: str | None = None
    llm_l3_key: str | None = None
    llm_l3_model: str = "gpt-4o"
    nvidia_api_key: str | None = None
    nvidia_api_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_llm_model: str = "meta/llama-3.1-8b-instruct"
    nvidia_use_as_l1: bool = False
    llm_monthly_budget_usd: float = Field(default=0.0, ge=0)
    llm_budget_alert_pct: int = Field(default=80, ge=0, le=100)
    llm_budget_action: str = "downgrade"

    default_ssh_user: str = "admin"
    default_ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_timeout: int = Field(default=10, ge=1, le=120)

    credential_store_path: str = "data/credentials.enc"
    credential_store_key: str = Field(default=_INSECURE_STORE_KEY)

    use_jira: bool = False
    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "NEXUS"

    use_servicenow: bool = False
    servicenow_url: str = ""
    servicenow_username: str = ""
    servicenow_password: str = ""
    servicenow_client_id: str = ""
    servicenow_client_secret: str = ""

    # Assets ITSM (ticketing via private API — same as operations but explicit flag)
    assets_itsm_enabled: bool = True

    alertmanager_url: str = "http://192.168.68.150:9094"
    prometheus_url: str = "http://192.168.68.150:9090"
    grafana_url: str = "http://192.168.68.150:3000"
    loki_url: str = "http://192.168.1.150:3100"
    loki_enabled: bool = False
    connector_timeout_seconds: int = Field(default=10, ge=1, le=120)
    connector_retry_count: int = Field(default=2, ge=0, le=10)

    outreach_enabled: bool = False
    outreach_email_address: str = ""
    outreach_sender_name: str = ""
    outreach_smtp_host: str = ""
    outreach_smtp_port: int = Field(default=465, ge=1, le=65535)
    outreach_smtp_user: str = ""
    outreach_smtp_password: str = ""
    outreach_imap_host: str = ""
    outreach_imap_port: int = Field(default=993, ge=1, le=65535)
    outreach_imap_user: str = ""
    outreach_imap_password: str = ""
    outreach_daily_cap_default: int = Field(default=20, ge=1, le=50)
    outreach_followup_delays_days: str = "4,9"
    outreach_data_dir: str = "data/outreach"
    prompt_data_dir: str = "data/prompts"
    prospecting_data_dir: str = "data/prospecting"
    prospecting_http_timeout_seconds: int = Field(default=12, ge=3, le=60)
    prospecting_user_agent: str = "Open-Nexus MunicipalProspector/1.0 (+https://assetsconsultores.es)"
    prospecting_max_pages_per_site: int = Field(default=4, ge=1, le=10)
    prospecting_enable_smtp_probe: bool = False
    # Binario local de Obscura (vendor/obscura/) para renderizar paginas con JS
    # real cuando el HTML estatico (httpx) no trae contenido util. Vacio =
    # autodetectar segun plataforma (obscura.exe en Windows, obscura en Linux/Mac).
    obscura_binary_path: str = ""
    local_llm_enabled: bool = False
    local_llm_base_url: str | None = None
    local_llm_model: str = ""
    local_llm_provider: str = "openai_compatible"
    local_llm_api_key: str = "not-needed"
    local_llm_timeout: int = Field(default=60, ge=5, le=600)
    local_llm_retries: int = Field(default=2, ge=0, le=10)
    brave_search_api_key: str | None = None
    brave_search_enabled: bool = False
    brave_search_rate_limit: float = Field(default=1.0, ge=0.0, le=60.0)
    google_places_api_key: str | None = None
    google_places_enabled: bool = False
    google_places_rate_limit: float = Field(default=0.5, ge=0.0, le=10.0)
    google_places_max_results_per_query: int = Field(default=20, ge=1, le=20)

    crm_odoo_enabled: bool = True
    crm_odoo_base_url: str = "http://127.0.0.1:8069"
    crm_odoo_database: str = "crm"
    crm_odoo_username: str = "admin"
    crm_odoo_password: str = ""
    crm_odoo_default_team: str = ""
    crm_odoo_default_stage: str = ""
    crm_odoo_source_label: str = "Nexus Outreach"
    assets_crm_enabled: bool = True
    assets_crm_base_url: str = "http://127.0.0.1:8000"
    assets_crm_username: str = ""
    assets_crm_password: str = ""
    assets_crm_source_label: str = "Nexus Outreach"

    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_file: Path | None = None

    desktop_port: int = Field(default=11430, ge=1024, le=65535)
    desktop_internal_token: str = Field(default="")

    @property
    def is_desktop(self) -> bool:
        return self.nexus_context == "desktop_app"

    @property
    def l0_url(self) -> str | None:
        return self.llm_l0_url or self.llm_api_base_url

    @property
    def l0_key(self) -> str:
        return self.llm_l0_key or self.llm_api_key or "not-needed"

    @property
    def l0_model(self) -> str:
        return self.llm_l0_model or self.llm_model or "local-model"

    @property
    def l1_url(self) -> str | None:
        if self.llm_l1_url:
            return self.llm_l1_url
        if self.nvidia_use_as_l1 and self.nvidia_api_key:
            return self.nvidia_api_base_url
        return None

    @property
    def l1_key(self) -> str | None:
        if self.llm_l1_key:
            return self.llm_l1_key
        if self.nvidia_use_as_l1 and self.nvidia_api_key:
            return self.nvidia_api_key
        return None

    @property
    def l1_model(self) -> str:
        if self.llm_l1_url and self.llm_l1_model:
            return self.llm_l1_model
        if self.nvidia_use_as_l1 and self.nvidia_api_key:
            return self.nvidia_llm_model
        return self.llm_l1_model

    @model_validator(mode="after")
    def _validar_seguridad_produccion(self) -> "AppConfig":
        if self.app_environment != "production":
            return self

        inseguros: list[str] = []
        if not self.secret_key or self.secret_key == _INSECURE_SECRET_KEY:
            inseguros.append("SECRET_KEY")
        if not self.credential_store_key or self.credential_store_key == _INSECURE_STORE_KEY:
            inseguros.append("CREDENTIAL_STORE_KEY")
        if "admin:changeme" in self.app_users:
            inseguros.append("APP_USERS")
        if not self.mongo_uri or "nexus123" in self.mongo_uri:
            inseguros.append("MONGO_URI")
        if not self.redis_password:
            inseguros.append("REDIS_PASSWORD")
        if self.session_secure_cookie is not True:
            inseguros.append("SESSION_SECURE_COOKIE")
        if self.outreach_enabled and not self.outreach_smtp_password:
            inseguros.append("OUTREACH_SMTP_PASSWORD")
        if self.outreach_enabled and not self.outreach_imap_password:
            inseguros.append("OUTREACH_IMAP_PASSWORD")
        if self.brave_search_enabled and not self.brave_search_api_key:
            inseguros.append("BRAVE_SEARCH_API_KEY")
        if self.google_places_enabled and not self.google_places_api_key:
            inseguros.append("GOOGLE_PLACES_API_KEY")

        if inseguros:
            raise ValueError(
                "NEXUS-UI no puede arrancar en produccion con configuracion insegura o incompleta: "
                + ", ".join(inseguros)
            )

        return self

    def parsed_users(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for entry in self.app_users.split(","):
            entry = entry.strip()
            if ":" in entry:
                user, pwd = entry.split(":", 1)
                result[user.strip()] = pwd.strip()
        return result

    def jira_configured(self) -> bool:
        return self.use_jira and bool(self.jira_url and self.jira_email and self.jira_api_token)

    def servicenow_configured(self) -> bool:
        return self.use_servicenow and bool(self.servicenow_url and self.servicenow_username)


cfg = AppConfig()
