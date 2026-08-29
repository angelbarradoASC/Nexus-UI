"""Cliente de embeddings local — mide similitud semántica entre dos textos
sin depender de una API de pago.

Modelo: `nomic-embed-text` (137M parámetros, embedding_length=768). No
confundir con `qwen3:8b` (chat/razonamiento — no genera embeddings). Vive
en el mismo servidor local que ya usa `LocalLLMClient` (192.168.68.150).

Cómo se instaló (documentado 2026-08-29, verificado en vivo, tardó ~30s
para 274MB):
    curl -X POST http://192.168.68.150:11434/api/pull \
      -H "Content-Type: application/json" \
      -d '{"model": "nomic-embed-text"}'

Verificar que está disponible:
    curl http://192.168.68.150:11434/api/tags
    # debe listar "nomic-embed-text" con "capabilities": ["embedding"]

Usa el endpoint NATIVO de Ollama (`/api/embeddings`), no el compatible con
OpenAI (`/v1/embeddings`) — probado en vivo en la misma máquina: el nativo
respondió en ~0.1s con el modelo ya cargado; el compatible tardó 13.8s en
la primera llamada (overhead del shim de compatibilidad, no compensa aquí
como sí compensó `think=False` para el chat — ver llm.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass(slots=True)
class LocalEmbeddingsSettings:
    base_url: str | None
    model: str = "nomic-embed-text"
    timeout: float = 120.0
    enabled: bool = False


class LocalEmbeddingsClient:
    """Cliente minimo contra el endpoint nativo de embeddings de Ollama."""

    def __init__(self, *, settings: LocalEmbeddingsSettings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled and self._settings.base_url and self._settings.model)

    async def embed(self, text: str) -> list[float] | None:
        """Devuelve el vector de embedding, o None si esta deshabilitado o falla
        (timeout, modelo no encontrado...) — nunca lanza, el llamante decide
        que hacer con una comparacion que no se pudo completar."""
        if not self.enabled or not text.strip():
            return None
        base = (self._settings.base_url or "").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=self._settings.timeout) as client:
                response = await client.post(
                    f"{base}/api/embeddings",
                    json={"model": self._settings.model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embedding = data.get("embedding")
                return list(embedding) if embedding else None
        except Exception as exc:
            logger.warning("LocalEmbeddingsClient | fallo generando embedding: {}", type(exc).__name__)
            return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """0.0 si los vectores no son comparables (longitud distinta, vacios,
    norma cero) — nunca lanza."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
