"""Core runtime bridge for the Open-Nexus desktop shell."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from desktop.path_setup import ensure_desktop_import_paths

ensure_desktop_import_paths()

from config import cfg
from desktop.config import DesktopSettings
from desktop.opennexus.models import OpenNexusResult
from desktop.runtime.assistant_runtime import DesktopAssistantRuntime
from desktop.runtime.bootstrap import set_current_runtime
from desktop.runtime.llm_provider_runtime import apply_desktop_provider_to_cfg
from desktop.storage.local_state import DesktopLocalState
from nexus.application.services.assistant_runtime_core import AssistantExecutionRequest
from nexus.api.dependencies.auth import build_runtime


class OpenNexusEngine:
    """Local-first shell inspired by Open Interpreter, wired to Nexus runtime."""

    def __init__(
        self,
        *,
        settings: DesktopSettings | None = None,
        desktop_runtime: DesktopAssistantRuntime | None = None,
        nexus_runtime: Any | None = None,
        history_limit: int = 40,
    ) -> None:
        self.settings = settings or DesktopSettings.from_env()
        self.desktop_runtime = desktop_runtime or DesktopAssistantRuntime(self.settings)
        set_current_runtime(self.desktop_runtime)
        self.local_state = DesktopLocalState(self.settings)
        self.provider_config = self.local_state.load_llm_provider_config()
        apply_desktop_provider_to_cfg(cfg, self.provider_config)
        self.nexus_runtime = nexus_runtime or build_runtime(cfg)
        self.history: deque[OpenNexusResult] = deque(maxlen=history_limit)
        for item in self.local_state.load_shell_history(limit=history_limit):
            self.history.append(item)

    async def execute(self, user_input: str) -> OpenNexusResult:
        """Resolve a desktop command and run it through Nexus chat orchestration."""
        resolution = self.desktop_runtime.resolve_user_input(user_input)
        result = await self.nexus_runtime.assistant_core.execute(
            AssistantExecutionRequest(
                message=user_input,
                user_id="open-nexus",
                mode="general",
                source_surface="desktop",
                resolution=resolution,
            )
        )
        shell_result = OpenNexusResult(
            user_input=user_input,
            resolution=result.resolution,
            response=result.response,
            agent=result.agent,
            status=result.status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.history.appendleft(shell_result)
        self.local_state.rewrite_shell_history(list(self.history))
        return shell_result

    def snapshot(self) -> dict[str, Any]:
        """Expose shell metadata for rendering and packaging."""
        description = self.desktop_runtime.describe()
        description["product"] = {
            "name": "Open-Nexus",
            "mode": "desktop-shell",
            "inspired_by": "Open Interpreter",
        }
        description["examples"] = self.examples()
        description["history"] = [item.to_dict() for item in list(self.history)[:8]]
        description["paths"] = {
            "root": str(self.local_state.root),
            "config": str(self.local_state.config_dir),
            "logs": str(self.local_state.logs_dir),
            "history": str(self.local_state.history_dir),
            "shell_history": str(self.local_state.shell_history_path),
        }
        description["remote_provider"] = self.provider_config.to_dict(mask_secret=True)
        return description

    def examples(self) -> list[str]:
        """Return curated example prompts from the desktop skill catalogue."""
        examples: list[str] = []
        for skill in self.desktop_runtime.skills.all():
            for example in skill.examples[:1]:
                if example not in examples:
                    examples.append(example)
        return examples[:8]
