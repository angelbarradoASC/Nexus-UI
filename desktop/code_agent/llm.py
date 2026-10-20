"""
desktop/code_agent/llm.py
-----------------------------
Modelo propio del agente de codigo (alternativa al router L0-L3 / Groq).

Motivo (medido el 2026-10-19): la cuenta de Groq tiene 8.000 tokens/min y un bucle
de agente la agota; los modelos locales de Ollama no tienen ese limite. Esta capa:

- `OllamaToolClient`: habla con /api/chat de Ollama (NO con /v1) porque solo asi se
  fija `num_ctx`; con el contexto por defecto de Ollama (4096) un bucle de agente se
  truncaria en silencio.
- `recover_text_tool_calls`: qwen2.5-coder (3B y 14B, medido) devuelve la llamada a la
  herramienta como TEXTO JSON (a veces dentro de ```json) en vez de `tool_calls`.
  Se recupera, pero SOLO si el nombre es una herramienta conocida del agente.
- `CodeLLM`: elige en cada llamada entre el modelo propio (si esta configurado en
  `code_settings.json`) y el router, y aplica la recuperacion a ambos.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
import uuid
from types import SimpleNamespace
from typing import Any

import httpx

logger = logging.getLogger("nexus.code_agent")

_FENCE = re.compile(r"```(?:json|tool_call|python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TAGGED = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _candidates(content: str) -> list[str]:
    """Trozos de texto que podrian ser JSON de una tool call."""
    text = content.strip()
    found = [m.group(1).strip() for m in _TAGGED.finditer(text)]
    found += [m.group(1).strip() for m in _FENCE.finditer(text)]
    found.append(text)
    return [c for c in found if c]


def _as_calls(parsed: Any) -> list[dict[str, Any]]:
    items = parsed if isinstance(parsed, list) else [parsed]
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        spec = item.get("function") if isinstance(item.get("function"), dict) else item
        name = spec.get("name")
        arguments = spec.get("arguments", spec.get("parameters", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if isinstance(name, str) and isinstance(arguments, dict):
            out.append({"name": name, "arguments": arguments})
    return out


def extract_text_tool_calls(content: str | None, tool_names: set[str]) -> list[dict[str, Any]]:
    """Tool calls (formato OpenAI) escritas como texto. Solo se aceptan nombres de
    `tool_names`: un texto cualquiera nunca se convierte en una herramienta desconocida."""
    if not content or not tool_names:
        return []
    for candidate in _candidates(content):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        calls = [c for c in _as_calls(parsed) if c["name"] in tool_names]
        if calls:
            return [_tool_call(c["name"], c["arguments"]) for c in calls]
    return []


def recover_text_tool_calls(response: Any, tools: list[dict[str, Any]] | None) -> Any:
    """Si la respuesta no trae tool_calls pero el texto es una llamada valida, la convierte."""
    if getattr(response, "error", None) or getattr(response, "tool_calls", None):
        return response
    names = {t.get("function", {}).get("name") for t in (tools or [])} - {None}
    calls = extract_text_tool_calls(getattr(response, "content", None), names)
    if not calls:
        return response
    logger.info("CodeAgent: tool call recuperada del texto del modelo (%s)", calls[0]["function"]["name"])
    response.tool_calls = calls
    response.content = ""
    return response


# ── Cliente de Ollama ────────────────────────────────────────────────────────

def _to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Formato OpenAI -> formato nativo de Ollama (arguments como objeto, content siempre texto)."""
    converted = copy.deepcopy(messages)
    for message in converted:
        if message.get("content") is None:
            message["content"] = ""
        message.pop("tool_call_id", None)
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    function["arguments"] = json.loads(arguments or "{}")
                except json.JSONDecodeError:
                    function["arguments"] = {}
            call.pop("id", None)
            call.pop("type", None)
    return converted


class OllamaToolClient:
    def __init__(
        self, base_url: str, model: str, *, num_ctx: int = 8192, think: bool | None = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        # Qwen3 "piensa" antes de cada respuesta: medido en el servidor, 327-459 tokens de
        # razonamiento = 58-72 s por paso; con think=False, 5,5 s. None = no enviar el parametro.
        self.think = think
        self._client = client

    async def call(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        body = {
            "model": self.model,
            "messages": _to_ollama_messages(messages),
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": kwargs.get("temperature", 0.1),
                "num_predict": int(kwargs.get("max_tokens") or 1200),
            },
        }
        if kwargs.get("tools"):
            body["tools"] = kwargs["tools"]
        if self.think is not None:
            body["think"] = self.think
        if kwargs.get("json"):
            body["format"] = "json"      # salida JSON obligatoria (expansion de la pregunta)
        timeout = max(float(kwargs.get("timeout") or 60.0), 300.0)   # un modelo local puede tardar en cargar
        started = time.monotonic()
        try:
            reply, data = await self._post(body, timeout)
            if reply.status_code >= 400 and "think" in str(data.get("error", "")).lower() and "think" in body:
                # Un modelo sin modo razonamiento rechaza el parametro: se reintenta sin el.
                body.pop("think")
                reply, data = await self._post(body, timeout)
        except Exception as exc:
            return self._result(error=f"ollama_error | {type(exc).__name__}: {exc}", started=started)
        if reply.status_code >= 400 or "error" in data:
            return self._result(error=f"ollama_http_{reply.status_code} | {str(data.get('error', ''))[:200]}", started=started)

        message = data.get("message") or {}
        calls = [
            _tool_call(c["function"]["name"], c["function"].get("arguments") or {})
            for c in message.get("tool_calls") or []
            if isinstance(c.get("function"), dict) and c["function"].get("name")
        ]
        content = _THINK.sub("", message.get("content") or "").strip()
        return self._result(content=content, tool_calls=calls or None, started=started)

    async def _post(self, body: dict[str, Any], timeout: float) -> tuple[Any, dict[str, Any]]:
        if self._client is not None:
            reply = await self._client.post(f"{self.base_url}/api/chat", json=body, timeout=timeout)
        else:
            async with httpx.AsyncClient() as client:
                reply = await client.post(f"{self.base_url}/api/chat", json=body, timeout=timeout)
        return reply, reply.json()

    def _result(self, *, started: float, content: str = "", tool_calls: Any = None, error: str | None = None) -> Any:
        return SimpleNamespace(
            error=error, content=content, tool_calls=tool_calls, level_used=0, model_used=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


# ── Seleccion en cada llamada ────────────────────────────────────────────────

class CodeLLM:
    """Mismo contrato que el router (`call(messages=..., **kwargs)`): modelo propio si esta
    configurado en los ajustes, router en caso contrario; con recuperacion de tool calls en texto."""

    def __init__(self, router: Any, settings: Any) -> None:
        self._router = router
        self._settings = settings

    def configured_model(self) -> dict[str, Any] | None:
        getter = getattr(self._settings, "llm", None)
        return getter() if callable(getter) else None

    async def call(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        own = self.configured_model()
        if own:
            client = OllamaToolClient(own["base_url"], own["model"], num_ctx=own["num_ctx"], think=own.get("think", False))
            response = await client.call(messages, **kwargs)
        elif self._router is not None:
            response = await self._router.call(messages=messages, **kwargs)
        else:
            return SimpleNamespace(error="no_llm | No hay modelo configurado ni router disponible", content="", tool_calls=None)
        return recover_text_tool_calls(response, kwargs.get("tools"))
