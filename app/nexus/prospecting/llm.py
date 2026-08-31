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


@dataclass(slots=True)
class LocalToolCallResult:
    content: str
    tool_calls: list[dict[str, Any]]
    error: str | None = None


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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        temp = temperature if temperature is not None else self._settings.temperature
        tokens = max_tokens if max_tokens is not None else self._settings.max_tokens

        if self._settings.provider == "ollama":
            # Endpoint NATIVO de Ollama, NO el compatible con OpenAI —
            # verificado en vivo con una respuesta real (no solo un "ok"
            # trivial): think=False via /v1/chat/completions NO elimina el
            # razonamiento del todo, se cuela dentro de "content" y agota
            # max_tokens ANTES de llegar a la respuesta real (bug real,
            # encontrado 2026-08-29). Via /api/chat nativo, think=False lo
            # elimina limpio — mismo modelo, misma llamada, cero fugas.
            base = (self._settings.base_url or "").rstrip("/").removesuffix("/v1")
            endpoint = f"{base}/api/chat"
            payload: dict[str, Any] = {
                "model": self._settings.model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": temp, "num_predict": tokens},
            }
        else:
            endpoint = self._endpoint("/chat/completions")
            payload = {"messages": messages, "temperature": temp, "max_tokens": tokens}
            if self._settings.model:
                payload["model"] = self._settings.model

        last_error: Exception | None = None
        for _ in range(max(self._settings.retries, 1)):
            try:
                async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                    response = await client.post(endpoint, headers=self._headers(), json=payload)
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

    async def chat_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LocalToolCallResult:
        """Como complete(), pero deja que el modelo pida usar herramientas.
        Solo soportado con provider="ollama" — Ollama ya sabe aplicar la
        plantilla de tool-calling propia del modelo (verificado en vivo con
        qwen3:8b, capabilities=['completion','tools','thinking']): nosotros
        solo mandamos `tools` y leemos message.tool_calls, que Ollama ya
        entrega parseado (arguments como dict, no como string JSON — a
        diferencia de OpenAI). Para continuar la conversacion tras ejecutar
        una herramienta, añade un mensaje {"role": "tool", "content": <texto>}
        y vuelve a llamar — verificado en vivo que el modelo usa ese
        resultado para la respuesta final."""
        if not self.enabled:
            return LocalToolCallResult(content="", tool_calls=[], error="LLM local deshabilitado")
        if self._settings.provider != "ollama":
            return LocalToolCallResult(
                content="", tool_calls=[],
                error=f"tool-calling no soportado para provider={self._settings.provider}",
            )

        base = (self._settings.base_url or "").rstrip("/").removesuffix("/v1")
        endpoint = f"{base}/api/chat"
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": False,
            "options": {"temperature": self._settings.temperature},
        }

        last_error: Exception | None = None
        for _ in range(max(self._settings.retries, 1)):
            try:
                async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                    response = await client.post(endpoint, headers=self._headers(), json=payload)
                    response.raise_for_status()
                    data = response.json()
                    message = data.get("message") or {}
                    return LocalToolCallResult(
                        content=str(message.get("content") or "").strip(),
                        tool_calls=message.get("tool_calls") or [],
                    )
            except Exception as exc:  # pragma: no cover - network variance
                last_error = exc
        logger.warning(
            "LocalLLMClient.chat_with_tools | fallo tras {} intentos: {}",
            self._settings.retries, type(last_error).__name__,
        )
        return LocalToolCallResult(content="", tool_calls=[], error=str(last_error) if last_error else "error desconocido")

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
