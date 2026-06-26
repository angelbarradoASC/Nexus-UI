"""Prompt management and persistence for Nexus."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nexus.prompts.catalogue import DEFAULT_PROMPTS, PromptDefinition


class PromptManager:
    """Store and resolve editable prompts for Nexus."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "overrides.json"

    async def list_prompts(self) -> dict[str, Any]:
        overrides = await self._load_overrides()
        prompts = []
        for definition in DEFAULT_PROMPTS.values():
            current = overrides.get(definition.key, definition.default_text)
            prompts.append(
                {
                    "key": definition.key,
                    "title": definition.title,
                    "group": definition.group,
                    "description": definition.description,
                    "default_text": definition.default_text,
                    "current_text": current,
                    "is_overridden": definition.key in overrides,
                }
            )
        prompts.sort(key=lambda item: (item["group"], item["title"]))
        return {"status": "success", "total": len(prompts), "prompts": prompts}

    async def get_prompt(self, key: str) -> dict[str, Any]:
        definition = self._require_definition(key)
        overrides = await self._load_overrides()
        current = overrides.get(key, definition.default_text)
        return {
            "status": "success",
            "prompt": {
                "key": definition.key,
                "title": definition.title,
                "group": definition.group,
                "description": definition.description,
                "default_text": definition.default_text,
                "current_text": current,
                "is_overridden": key in overrides,
            },
        }

    async def update_prompt(self, key: str, text: str) -> dict[str, Any]:
        self._require_definition(key)
        overrides = await self._load_overrides()
        overrides[key] = text.strip()
        await self._save_overrides(overrides)
        return await self.get_prompt(key)

    async def reset_prompt(self, key: str) -> dict[str, Any]:
        self._require_definition(key)
        overrides = await self._load_overrides()
        overrides.pop(key, None)
        await self._save_overrides(overrides)
        return await self.get_prompt(key)

    async def resolve_prompt(self, key: str) -> str:
        definition = self._require_definition(key)
        overrides = await self._load_overrides()
        return overrides.get(key, definition.default_text)

    def resolve_prompt_sync(self, key: str) -> str:
        definition = self._require_definition(key)
        overrides = self._load_overrides_sync()
        return overrides.get(key, definition.default_text)

    async def _load_overrides(self) -> dict[str, str]:
        return await asyncio.to_thread(self._load_overrides_sync)

    def _load_overrides_sync(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(k): str(v) for k, v in payload.items()}

    async def _save_overrides(self, overrides: dict[str, str]) -> None:
        await asyncio.to_thread(
            self._path.write_text,
            json.dumps(overrides, ensure_ascii=False, indent=2),
            "utf-8",
        )

    @staticmethod
    def _require_definition(key: str) -> PromptDefinition:
        if key not in DEFAULT_PROMPTS:
            raise KeyError(key)
        return DEFAULT_PROMPTS[key]


_DEFAULT_MANAGER = PromptManager(Path("data/prompts"))


def set_default_prompt_manager(manager: PromptManager) -> None:
    """Replace the module-level prompt manager used by sync prompt resolution."""
    global _DEFAULT_MANAGER
    _DEFAULT_MANAGER = manager


def resolve_prompt_sync(key: str) -> str:
    """Resolve prompt text synchronously for modules that build prompts inline."""
    return _DEFAULT_MANAGER.resolve_prompt_sync(key)
