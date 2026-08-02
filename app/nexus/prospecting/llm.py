"""Local LLM client for prospecting workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from nexus.utils.llm_json import parse_llm_json


@dataclass(slots=True)
class LocalLLMSettings:
    base_url: str | None
    model: str
    provider: str = "openai_compatible"
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout: float = 60.0
    retries: int = 2
    enabled: bool = False


class LocalLLMClient:
    """Small OpenAI-compatible client for local reasoning tasks."""

    def __init__(
        self,
        *,
        settings: LocalLLMSettings,
        api_key: str = "not-needed",
        dry_run: bool = False,
    ) -> None:
        self._settings = settings
        self._api_key = api_key or "not-needed"
        self._dry_run = dry_run

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled and self._settings.base_url and self._settings.model)

    @property
    def descriptor(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self._settings.provider,
            "base_url": self._settings.base_url or "",
            "model": self._settings.model,
            "dry_run": self._dry_run,
        }

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if self._dry_run or not self.enabled:
            return ""

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else self._settings.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self._settings.max_tokens,
        }
        if self._settings.model:
            payload["model"] = self._settings.model

        last_error: Exception | None = None
        for _ in range(max(self._settings.retries, 1)):
            try:
                async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                    response = await client.post(
                        self._endpoint("/chat/completions"),
                        headers=self._headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    if message := data.get("message"):
                        return str(message.get("content") or "").strip()
                    choices = data.get("choices") or []
                    if not choices:
                        return ""
                    message = choices[0].get("message") or {}
                    return str(message.get("content") or message.get("reasoning") or "").strip()
            except Exception as exc:  # pragma: no cover - network variance
                last_error = exc
        if last_error is not None:
            logger.warning("LocalLLMClient | fallo tras {} intentos — degradado: {}", self._settings.retries, type(last_error).__name__)
            return ""
        return ""

    async def extract_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
    ) -> dict[str, Any]:
        if self._dry_run or not self.enabled:
            return {}

        schema_block = json.dumps(schema_hint, indent=2, ensure_ascii=False)
        response = await self.complete(
            system_prompt=system_prompt,
            user_prompt=(
                f"{user_prompt}\n\n"
                "Devuelve solo JSON válido, sin explicaciones ni markdown.\n"
                f"Usa esta estructura como guía:\n{schema_block}"
            ),
            temperature=0.1,
        )
        return self._parse_json_response(response)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self, path: str) -> str:
        base = (self._settings.base_url or "").rstrip("/")
        if not base:
            raise RuntimeError("LOCAL_LLM_BASE_URL no configurado")
        if base.endswith("/v1"):
            return f"{base}{path}"
        if self._settings.provider in {"ollama", "lmstudio", "openai_compatible"}:
            return f"{base}/v1{path}"
        if self._settings.provider == "braingel":
            if path == "/chat/completions":
                return f"{base}/chat"
            return f"{base}{path}"
        return f"{base}{path}"

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        return parse_llm_json(text) or {}
