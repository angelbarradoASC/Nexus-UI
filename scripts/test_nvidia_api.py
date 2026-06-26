"""Smoke test for NVIDIA API Catalog / hosted NIM endpoints."""

from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> int:
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    base_url = os.environ.get(
        "NVIDIA_API_BASE_URL",
        "https://integrate.api.nvidia.com/v1",
    ).rstrip("/")
    model = os.environ.get(
        "NVIDIA_LLM_MODEL",
        "meta/llama-3.1-8b-instruct",
    ).strip()

    if not api_key:
        print("Falta NVIDIA_API_KEY en el entorno.", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        models_response = client.get(f"{base_url}/models", headers=headers)
        models_response.raise_for_status()
        models_payload = models_response.json()
        available_models = [
            item.get("id", "")
            for item in models_payload.get("data", [])
            if item.get("id")
        ]

        print("Modelos disponibles:")
        print(json.dumps(available_models[:20], indent=2, ensure_ascii=False))

        if model not in available_models:
            print(
                f"Advertencia: el modelo configurado '{model}' no aparece en /models.",
                file=sys.stderr,
            )

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
        completion_payload = completion_response.json()
        message = completion_payload["choices"][0]["message"]["content"]

    print("\nRespuesta de prueba:")
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
