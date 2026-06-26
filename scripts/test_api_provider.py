"""Generic smoke test for OpenAI-compatible API providers."""

from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> int:
    base_url = os.environ.get("TEST_LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("TEST_LLM_API_KEY", "").strip()
    model = os.environ.get("TEST_LLM_MODEL", "").strip()

    if not base_url:
        print("Falta TEST_LLM_BASE_URL.", file=sys.stderr)
        return 1
    if not api_key:
        print("Falta TEST_LLM_API_KEY.", file=sys.stderr)
        return 1
    if not model:
        print("Falta TEST_LLM_MODEL.", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "https://nexus.local"
        headers["X-Title"] = "Nexus"

    with httpx.Client(timeout=30.0) as client:
        models_url = f"{base_url}/models"
        model_status = "not_checked"
        available_models: list[str] = []
        try:
            models_response = client.get(models_url, headers=headers)
            models_response.raise_for_status()
            models_payload = models_response.json()
            available_models = [
                item.get("id", "")
                for item in models_payload.get("data", [])
                if item.get("id")
            ]
            model_status = "ok"
        except Exception as exc:
            model_status = f"warning: {type(exc).__name__}"

        print("Estado /models:", model_status)
        if available_models:
            print("Primeros modelos:")
            print(json.dumps(available_models[:20], indent=2, ensure_ascii=False))

        completion_response = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Responde solo con OK si recibes este mensaje.",
                    }
                ],
                "temperature": 0.0,
                "max_tokens": 32,
            },
        )
        completion_response.raise_for_status()
        payload = completion_response.json()
        message_payload = payload["choices"][0]["message"]
        message = message_payload.get("content") or message_payload.get("reasoning") or ""

    print("\nRespuesta:")
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
