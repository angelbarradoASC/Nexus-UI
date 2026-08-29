"""
app/agents/llm_router.py
-------------------------
Router LLM con 4 niveles (L0→L3), fallback automático, retries con
backoff exponencial y métricas Prometheus.

Estándares aplicados:
  - 05_IA_AGENTES.md §1: LLMLevel como Pydantic BaseModel frozen
  - 01_PYTHON_GENERAL.md §4.5: Prioridad como StrEnum
  - 01_PYTHON_GENERAL.md §3: cfg centralizado
  - AsyncClient compartido por instancia (no uno por llamada)
  - Retries para timeout / 429 / 5xx con backoff exponencial
  - Métricas: latencia, nivel usado, fallos por nivel
"""

from __future__ import annotations

import asyncio
import json as _json
import time
from collections.abc import AsyncGenerator
from enum import StrEnum
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict

from config import cfg


# ── Enums ─────────────────────────────────────────────────────────────────────

class Prioridad(StrEnum):
    COSTE = "cost"       # L0 → L1 → L2 → L3 (más barato primero)
    VELOCIDAD = "speed"  # Directo al nivel más alto disponible
    BALANCE = "balanced" # Empieza en L2


# ── Modelos de datos ──────────────────────────────────────────────────────────

class LLMLevel(BaseModel):
    """Configuración de un nivel LLM — inmutable después de crearse."""
    model_config = ConfigDict(frozen=True)

    level: int
    name: str
    url: str
    api_key: str
    model: str
    enabled: bool = True
    cost_per_1k_tokens: float = 0.0
    timeout: int = 60


class LLMResponse(BaseModel):
    """Resultado de una llamada al router."""
    content: str
    level_used: int
    model_used: str
    nivel_name: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: int = 0
    error: str | None = None
    retries_used: int = 0
    retry_after: float | None = None   # segundos sugeridos por el proveedor en 429
    tool_calls: list[dict[str, Any]] | None = None  # tool calls devueltos por el modelo (formato OpenAI)


# ── Configuración de reintentos ───────────────────────────────────────────────

_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2
_BACKOFF_BASE = 0.5  # segundos


# ── Métricas internas (Prometheus-compatible) ─────────────────────────────────

class _RouterMetrics:
    """Contadores en memoria para observabilidad interna."""

    def __init__(self) -> None:
        self.calls_total: dict[str, int] = {}
        self.failures_total: dict[str, int] = {}
        self.latency_sum_ms: dict[str, float] = {}

    def record_success(self, nivel_name: str, latency_ms: int) -> None:
        self.calls_total[nivel_name] = self.calls_total.get(nivel_name, 0) + 1
        self.latency_sum_ms[nivel_name] = (
            self.latency_sum_ms.get(nivel_name, 0.0) + latency_ms
        )

    def record_failure(self, nivel_name: str) -> None:
        self.failures_total[nivel_name] = self.failures_total.get(nivel_name, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": dict(self.calls_total),
            "failures": dict(self.failures_total),
            "avg_latency_ms": {
                n: round(self.latency_sum_ms[n] / self.calls_total[n], 1)
                for n in self.calls_total
                if self.calls_total[n] > 0
            },
        }


# ── LLMRouter ─────────────────────────────────────────────────────────────────

class LLMRouter:
    """
    Router central de modelos LLM para NEXUS-UI.

    Gestiona 4 niveles con fallback automático, reintentos con backoff
    exponencial y métricas internas.

    No crear directamente: usar get_router() para obtener el singleton.
    """

    def __init__(self) -> None:
        self.prioridad = Prioridad(cfg.llm_priority)
        self._levels: dict[int, LLMLevel] = {}
        self._client: httpx.AsyncClient | None = None
        self.metrics = _RouterMetrics()
        self._watchdog: Any | None = None   # LevelWatchdog — import lazy para evitar circular
        self._cargar_niveles()

        logger.info(
            "LLMRouter inicializado | prioridad={} | niveles={}",
            self.prioridad,
            sorted(self._levels.keys()),
        )

    # ── Inicialización ────────────────────────────────────────────────────────

    def _cargar_niveles(self) -> None:
        # L0 — Local
        if l0_url := cfg.l0_url:
            self._levels[0] = LLMLevel(
                level=0, name="L0-Local",
                url=l0_url, api_key=cfg.l0_key, model=cfg.l0_model,
                cost_per_1k_tokens=0.0, timeout=120,
            )

        # L1 — Groq (openai/gpt-oss-20b) — OpenRouter free (50/dia) se agoto
        # probando esta noche; Groq da 1000-14400/dia gratis, sin tarjeta.
        # Groq retiro toda la familia Llama de su catalogo (llama-3.1-8b-instant
        # devolvia 404 model_not_found) — migrado a gpt-oss-20b.
        if cfg.l1_url and cfg.l1_key:
            self._levels[1] = LLMLevel(
                level=1, name="L1-Groq-GptOss20B",
                url=cfg.l1_url, api_key=cfg.l1_key, model=cfg.l1_model,
                cost_per_1k_tokens=0.0, timeout=30,
            )

        # L2 — Groq (qwen/qwen3.8-27b) — antes llama-3.3-70b-versatile, tambien
        # retirado por Groq (404 model_not_found). Qwen en vez de otro gpt-oss
        # para que la escalada L2 tenga un proveedor/familia realmente distinto
        # de L1 y L3, no solo un tamano distinto del mismo modelo.
        if cfg.llm_l2_url and cfg.llm_l2_key:
            self._levels[2] = LLMLevel(
                level=2, name="L2-Groq-Qwen27B",
                url=cfg.llm_l2_url, api_key=cfg.llm_l2_key, model=cfg.llm_l2_model,
                cost_per_1k_tokens=0.0, timeout=30,
            )

        # L3 — Groq (gpt-oss-120b)
        if cfg.llm_l3_url and cfg.llm_l3_key:
            self._levels[3] = LLMLevel(
                level=3, name="L3-Groq-GptOss120B",
                url=cfg.llm_l3_url, api_key=cfg.llm_l3_key, model=cfg.llm_l3_model,
                cost_per_1k_tokens=0.0, timeout=30,
            )

        if not self._levels:
            logger.warning(
                "LLMRouter: ningún nivel configurado. "
                "Define LLM_L0_URL (o LLM_API_BASE_URL) en .env."
            )

    # ── AsyncClient compartido ────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Devuelve el AsyncClient compartido.
        Se crea en el primer uso y se reutiliza para todas las llamadas.
        Cerrar explícitamente con close() al apagar.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def start_watchdog(self) -> None:
        """Arranca el watchdog de salud. Llamar tras crear el router en el lifespan."""
        from agents.llm_watchdog import LevelWatchdog
        self._watchdog = LevelWatchdog(self._levels)
        await self._watchdog.start()

    async def close(self) -> None:
        """Cerrar watchdog y cliente HTTP. Llamar en el lifespan de FastAPI."""
        if self._watchdog is not None:
            await self._watchdog.stop()
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.debug("LLMRouter AsyncClient cerrado")

    @staticmethod
    def _build_headers(nivel: LLMLevel) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {nivel.api_key}"}
        if "openrouter.ai" in nivel.url:
            headers["HTTP-Referer"] = "https://nexus.local"
            headers["X-Title"] = "Nexus"
        return headers

    @staticmethod
    def _is_braingel(nivel: LLMLevel) -> bool:
        return nivel.url.rstrip("/").endswith(":11445") or "braingel" in nivel.model.lower()

    def _chat_endpoint(self, nivel: LLMLevel) -> str:
        if self._is_braingel(nivel):
            return f"{nivel.url.rstrip('/')}/chat"
        return f"{nivel.url.rstrip('/')}/chat/completions"

    # ── Llamada principal ─────────────────────────────────────────────────────

    async def call(
        self,
        messages: list[dict[str, str]],
        *,
        min_level: int = 0,
        preferred_level: int = 0,
        speed_level: int = 2,
        temperature: float = 0.45,
        max_tokens: int = 1200,
        timeout: float = 120.0,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> LLMResponse:
        """
        Llama al LLM con la estrategia configurada + fallback automático.

        Args:
            messages:        Lista de mensajes formato OpenAI.
            min_level:       Nivel mínimo aceptable.
            preferred_level: Nivel preferido en modo coste.
            speed_level:     Nivel inicial en modo velocidad.
            temperature:     Temperatura del modelo (0=determinista).
            max_tokens:      Tokens máximos de respuesta.
            timeout:         Timeout por intento en segundos.
            tools:           Definiciones de funciones (formato OpenAI tools) para tool calling.
            tool_choice:     "auto" | "required" | {"type":"function",...} — ver docs OpenRouter.

        Returns:
            LLMResponse con content y metadatos. error!=None si todo falló.
        """
        start_level = self._calcular_nivel_inicio(preferred_level, speed_level, min_level)
        candidate_levels = self._candidatos(start_level)

        if not candidate_levels:
            return LLMResponse(
                content="Error: no hay modelos LLM configurados.",
                level_used=-1, model_used="none",
                error="no_levels_configured",
            )

        last_error: str = ""
        for lv_num in candidate_levels:
            nivel = self._levels[lv_num]
            result = await self._llamar_con_retry(
                nivel, messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                tools=tools,
                tool_choice=tool_choice,
            )
            if result.error is None:
                if lv_num > start_level:
                    logger.warning(
                        "LLMRouter escalado | L{}→L{} | {}",
                        start_level, lv_num, nivel.name,
                    )
                return result
            last_error = result.error

        return LLMResponse(
            content=f"Todos los niveles LLM fallaron. Último error: {last_error}",
            level_used=-1, model_used="none",
            error=last_error,
        )

    async def call_stream(
        self,
        messages: list[dict[str, str]],
        *,
        min_level: int = 0,
        preferred_level: int = 0,
        speed_level: int = 2,
        temperature: float = 0.45,
        max_tokens: int = 1800,
        timeout: float = 120.0,
    ) -> AsyncGenerator[str, None]:
        """
        Versión streaming de call(). Yield de chunks de texto conforme llegan del LLM.
        Usa el nivel preferido sin fallback (fallback rompería el stream parcial).
        """
        start_level = self._calcular_nivel_inicio(preferred_level, speed_level, min_level)
        candidates  = self._candidatos(start_level)

        if not candidates:
            yield "Error: no hay modelos LLM configurados."
            return

        nivel = self._levels[candidates[0]]
        payload = {
            "model":       nivel.model,
            "messages":    messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
            "stream":      True,
        }

        t0 = time.monotonic()
        try:
            client = await self._get_client()
            async with client.stream(
                "POST",
                self._chat_endpoint(nivel),
                headers=self._build_headers(nivel),
                json=payload,
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            ) as response:
                response.raise_for_status()
                if self._is_braingel(nivel):
                    data = await response.aread()
                    try:
                        chunk_data = _json.loads(data.decode("utf-8"))
                        content = ((chunk_data.get("message") or {}).get("content") or "").strip()
                        if content:
                            yield content
                    except _json.JSONDecodeError:
                        pass
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk_data = _json.loads(raw)
                        delta = chunk_data["choices"][0].get("delta", {})
                        if content := delta.get("content", ""):
                            yield content
                    except (KeyError, IndexError, _json.JSONDecodeError):
                        continue

            latency_ms = int((time.monotonic() - t0) * 1000)
            self.metrics.record_success(nivel.name, latency_ms)
            logger.debug("LLMRouter stream OK | nivel={} | latencia={}ms", nivel.name, latency_ms)

        except httpx.HTTPStatusError as e:
            self.metrics.record_failure(nivel.name)
            logger.error("LLMRouter stream HTTP {} | nivel={}", e.response.status_code, nivel.name)
            yield f"\n[Error HTTP {e.response.status_code}]"
        except Exception as e:
            self.metrics.record_failure(nivel.name)
            logger.error("LLMRouter stream error | nivel={} | {}", nivel.name, e)
            yield "\n[Error de conexión con el modelo]"

    # ── Lógica de escalado ────────────────────────────────────────────────────

    def _calcular_nivel_inicio(
        self, preferred: int, speed: int, min_level: int
    ) -> int:
        match self.prioridad:
            case Prioridad.VELOCIDAD:
                start = speed
            case Prioridad.BALANCE:
                start = max(preferred, 2)
            case _:  # COSTE
                start = preferred
        return max(start, min_level)

    def _candidatos(self, desde: int) -> list[int]:
        sorted_levels = sorted(self._levels.keys())
        desde_start = [lv for lv in sorted_levels if lv >= desde]
        fallback = desde_start or sorted_levels

        if self._watchdog is None:
            return fallback

        vivos = [lv for lv in fallback if self._watchdog.is_healthy(lv)]
        if vivos:
            return vivos

        # Todos los niveles conocidos como caídos: intenta igualmente (modo degradado)
        logger.warning("LLMRouter | todos los niveles caídos — modo degradado")
        return fallback

    # ── Llamada a un nivel con reintentos ─────────────────────────────────────

    async def _llamar_con_retry(
        self,
        nivel: LLMLevel,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> LLMResponse:
        """
        Intenta llamar a un nivel con backoff exponencial.
        Reintenta en timeout / 429 / 5xx. No reintenta en 4xx (salvo 429).
        """
        ultimo_error: str = ""

        for intento in range(_MAX_RETRIES + 1):
            if intento > 0:
                # Solo llega aquí en errores 5xx o timeout — backoff exponencial
                espera = _BACKOFF_BASE * (2 ** (intento - 1))
                logger.debug(
                    "LLMRouter reintento | nivel={} | intento={} | espera={}s",
                    nivel.name, intento, round(espera, 1),
                )
                await asyncio.sleep(espera)

            result = await self._llamar_nivel(
                nivel, messages, temperature, max_tokens, timeout,
                tools=tools, tool_choice=tool_choice,
            )

            if result.error is None:
                result = result.model_copy(update={"retries_used": intento})
                return result

            ultimo_error = result.error
            # 429: escalar inmediatamente al siguiente nivel — no reintentar el mismo
            if "http_429" in ultimo_error:
                break
            # Timeout: escalar — no tiene sentido reintentar si el nivel está lento
            if "timeout" in ultimo_error:
                break
            # Otros 4xx: sin reintentos
            if "http_4" in ultimo_error:
                break

        self.metrics.record_failure(nivel.name)
        # Enfriar el nivel en cooldown si fue rate-limit
        if self._watchdog is not None and "http_429" in ultimo_error:
            self._watchdog.mark_cooldown(nivel.level)
        return LLMResponse(
            content="", level_used=nivel.level, model_used=nivel.model,
            nivel_name=nivel.name, error=ultimo_error,
            retries_used=intento,
        )

    async def _llamar_nivel(
        self,
        nivel: LLMLevel,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> LLMResponse:
        """Llamada HTTP a un nivel concreto (sin reintento)."""
        payload = {
            "model": nivel.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        t0 = time.monotonic()
        try:
            client = await self._get_client()
            response = await client.post(
                self._chat_endpoint(nivel),
                headers=self._build_headers(nivel),
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()

            latency_ms = int((time.monotonic() - t0) * 1000)
            data = response.json()
            if self._is_braingel(nivel):
                message = data.get("message") or {}
                raw_content = message.get("content") or ""
                usage = {}
            else:
                message = data["choices"][0]["message"]
                raw_content = message.get("content") or message.get("reasoning") or ""
                usage = data.get("usage", {})
            content = raw_content.strip()
            tool_calls = message.get("tool_calls") if not self._is_braingel(nivel) else None

            self.metrics.record_success(nivel.name, latency_ms)
            logger.debug(
                "LLMRouter OK | nivel={} | tokens={}/{} | latencia={}ms | tool_calls={}",
                nivel.name,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                latency_ms,
                len(tool_calls) if tool_calls else 0,
            )

            return LLMResponse(
                content=content,
                level_used=nivel.level,
                model_used=nivel.model,
                nivel_name=nivel.name,
                tokens_input=usage.get("prompt_tokens", 0),
                tokens_output=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                tool_calls=tool_calls or None,
            )

        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - t0) * 1000)
            error = f"timeout | nivel={nivel.name} | {latency_ms}ms"
            logger.warning("LLMRouter timeout | nivel={} | {}ms", nivel.name, latency_ms)
            return LLMResponse(
                content="", level_used=nivel.level, model_used=nivel.model,
                nivel_name=nivel.name, error=error,
            )

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            error = f"http_{status} | nivel={nivel.name}"
            retry_after: float | None = None
            if status == 429:
                try:
                    retry_after = float(e.response.headers.get("Retry-After", 0) or 0)
                except (ValueError, TypeError):
                    retry_after = None
            logger.warning("LLMRouter HTTP {} | nivel={} | retry_after={}s", status, nivel.name, retry_after)
            return LLMResponse(
                content="", level_used=nivel.level, model_used=nivel.model,
                nivel_name=nivel.name, error=error, retry_after=retry_after,
            )

        except Exception as e:
            error = f"error_inesperado | nivel={nivel.name} | {type(e).__name__}: {e}"
            logger.error("LLMRouter error inesperado | nivel={} | {}", nivel.name, e)
            return LLMResponse(
                content="", level_used=nivel.level, model_used=nivel.model,
                nivel_name=nivel.name, error=error,
            )

    # ── Helpers públicos ──────────────────────────────────────────────────────

    def available_levels(self) -> list[int]:
        return sorted(k for k, v in self._levels.items() if v.enabled)

    def metrics_snapshot(self) -> dict[str, Any]:
        return self.metrics.snapshot()

    def watchdog_snapshot(self) -> dict[str, Any]:
        """Estado de salud de los niveles según el watchdog."""
        if self._watchdog is None:
            return {"enabled": False}
        return {"enabled": True, **self._watchdog.status_snapshot()}


# ── Singleton global ──────────────────────────────────────────────────────────

_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    """Devuelve (o crea) la instancia global del router."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


async def reset_router() -> None:
    """Reset the global router so desktop config changes can be applied live."""
    global _router
    if _router is not None:
        await _router.close()
    _router = None
