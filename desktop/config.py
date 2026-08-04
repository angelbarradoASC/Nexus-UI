"""Configuration helpers for Nexus Desktop."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DesktopSettings:
    """Resolved desktop runtime settings."""

    app_port: int = 11430
    nexus_context: str = "desktop_app"
    host: str = "127.0.0.1"
    startup_timeout_seconds: int = 15
    monitoring_interval_seconds: int = 30
    desktop_internal_token: str = ""
    startup_route: str = "/open-nexus"
    open_operator_on_start: bool = True
    debug: bool = False
    local_data_root: str = ""

    @property
    def local_url(self) -> str:
        return f"http://{self.host}:{self.app_port}"

    @property
    def startup_url(self) -> str:
        route = self.startup_route if self.startup_route.startswith("/") else f"/{self.startup_route}"
        return f"{self.local_url}{route}"

    @property
    def resolved_local_data_root(self) -> Path:
        if self.local_data_root:
            return Path(self.local_data_root).expanduser().resolve()
        return (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Open-Nexus").resolve()

    @property
    def config_dir(self) -> Path:
        return self.resolved_local_data_root / "config"

    @property
    def logs_dir(self) -> Path:
        return self.resolved_local_data_root / "logs"

    @property
    def history_dir(self) -> Path:
        return self.resolved_local_data_root / "history"

    @property
    def llm_provider_config_path(self) -> Path:
        return self.config_dir / "llm_provider.json"

    @property
    def monitoring_config_db_path(self) -> Path:
        return self.config_dir / "monitoring_integrations.db"

    @property
    def llm_router_config_path(self) -> Path:
        return self.config_dir / "llm_router.json"

    @property
    def sales_config_path(self) -> Path:
        return self.config_dir / "sales_config.json"

    @property
    def campaign_config_path(self) -> Path:
        return self.config_dir / "campaign_config.json"

    @property
    def itsm_config_path(self) -> Path:
        return self.config_dir / "itsm_config.json"

    @classmethod
    def from_env(cls) -> "DesktopSettings":
        """Build desktop settings from environment variables."""
        return cls(
            app_port=int(os.environ.get("APP_PORT", "11430")),
            nexus_context=os.environ.get("NEXUS_CONTEXT", "desktop_app"),
            host=os.environ.get("DESKTOP_HOST", "127.0.0.1"),
            startup_timeout_seconds=int(os.environ.get("DESKTOP_STARTUP_TIMEOUT", "15")),
            monitoring_interval_seconds=int(os.environ.get("DESKTOP_MONITOR_INTERVAL", "30")),
            desktop_internal_token=os.environ.get("DESKTOP_INTERNAL_TOKEN", ""),
            startup_route=os.environ.get("DESKTOP_STARTUP_ROUTE", "/open-nexus"),
            open_operator_on_start=os.environ.get("DESKTOP_OPEN_OPERATOR_ON_START", "true").lower() in {"1", "true", "yes", "on"},
            debug=os.environ.get("DEBUG", "").lower() in {"1", "true", "yes", "on"},
            local_data_root=os.environ.get("OPEN_NEXUS_DATA_DIR", ""),
        )
