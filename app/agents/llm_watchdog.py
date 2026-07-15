"""
app/agents/llm_watchdog.py
---------------------------
Watchdog proactivo para los niveles del LLM Router.

Sondea cada nivel con un GET ligero (sin gastar tokens) antes de que llegue
la primera llamada real. Mantiene un mapa de salud que el router consume en
_candidatos() para saltar directamente al primer nivel vivo.

Máquina de estados por nivel:
  UNKNOWN (arranque optimista)
    → 1 sondeo OK  → UP
    → FAIL_THRESHOLD fallos seguidos → DOWN

  UP
    → FAIL_THRESHOLD fallos seguidos → DOWN  (warning log)

  DOWN
    → RECOVER_THRESHOLD éxitos seguidos → UP  (info log)
    → intervalo de re-sondeo más corto (INTERVAL_DEGRADED)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger


class LevelWatchdog:
    """Sondeo periódico y no bloqueante de la disponibilidad de cada nivel LLM."""

    PROBE_TIMEOUT     = 4.0   # segundos por intento
    FAIL_THRESHOLD    = 2     # fallos consecutivos para declarar DOWN
    RECOVER_THRESHOLD = 1     # éxitos consecutivos para declarar UP desde DOWN
    INTERVAL_HEALTHY  = 30    # segundos entre sondeos cuando todo está UP
    INTERVAL_DEGRADED = 10    # segundos entre sondeos cuando hay algún nivel DOWN

    def __init__(self, levels: dict[int, Any]) -> None:
        # levels: dict[int, LLMLevel] — aceptamos Any para evitar importación circular
        self._levels = levels
        self._health: dict[int, bool] = {}           # None-ausente = optimista
        self._fails:  dict[int, int]  = {}
        self._oks:    dict[int, int]  = {}
        self._last_ts: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}  # monotonic timestamp de fin de cooldown
        self._task: asyncio.Task[None] | None = None

    # ── API pública ──────────────────────────────────────────────────────────

    def is_healthy(self, level: int) -> bool:
        """Devuelve True si el nivel está UP o aún no ha sido sondeado (optimista)."""
        # Cooldown activo → caído temporalmente
        if level in self._cooldown_until:
            if time.monotonic() < self._cooldown_until[level]:
                return False
            del self._cooldown_until[level]
        return self._health.get(level, True)

    def mark_cooldown(self, level: int, seconds: float = 60.0) -> None:
        """
        Marca un nivel como no disponible durante `seconds` segundos.
        Llamado por el router cuando agota reintentos en un 429.
        Se recupera automáticamente al expirar sin necesidad de re-sondeo.
        """
        self._cooldown_until[level] = time.monotonic() + seconds
        name = self._levels[level].name if level in self._levels else str(level)
        logger.warning(
            "LLM Watchdog | L{} {} en cooldown por 429 — disponible en {}s",
            level, name, int(seconds),
        )

    def status_snapshot(self) -> dict[str, Any]:
        """Estado completo para /health o Prometheus."""
        now = time.monotonic()
        entries = {}
        for lv in sorted(self._levels):
            nivel = self._levels[lv]
            cooldown_remaining = max(0.0, self._cooldown_until.get(lv, 0) - now)
            entries[str(lv)] = {
                "name":              nivel.name,
                "healthy":           self.is_healthy(lv),
                "fails":             self._fails.get(lv, 0),
                "oks":               self._oks.get(lv, 0),
                "cooldown_remaining_s": round(cooldown_remaining, 1) if cooldown_remaining > 0 else None,
                "last_probe_s_ago":  (
                    round(now - self._last_ts[lv], 1)
                    if lv in self._last_ts else None
                ),
            }
        return {"levels": entries}

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Sondeo inmediato al arrancar + loop periódico en background."""
        await self._probe_all()
        self._task = asyncio.create_task(self._loop(), name="llm-watchdog")
        logger.info(
            "LLM Watchdog arrancado | niveles={} | intervalo_ok={}s | intervalo_down={}s",
            sorted(self._levels.keys()),
            self.INTERVAL_HEALTHY,
            self.INTERVAL_DEGRADED,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.debug("LLM Watchdog detenido")

    # ── Loop y sondeo ────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while True:
            any_down = any(not v for v in self._health.values())
            interval = self.INTERVAL_DEGRADED if any_down else self.INTERVAL_HEALTHY
            await asyncio.sleep(interval)
            await self._probe_all()

    async def _probe_all(self) -> None:
        for lv, nivel in self._levels.items():
            ok = await self._probe(nivel)
            self._last_ts[lv] = time.monotonic()
            self._update(lv, ok, nivel.name)

    async def _probe(self, nivel: Any) -> bool:
        """
        GET ligero al endpoint de listado del proveedor — no gasta tokens.
        Ollama:  GET /api/tags
        OpenAI-compatible: GET /models
        401/403 se consideran UP (servidor vivo, problema de auth).
        """
        is_ollama = "11434" in nivel.url or "ollama" in nivel.url.lower()
        if is_ollama:
            url = f"{nivel.url.rstrip('/')}/api/tags"
            headers: dict[str, str] = {}
        else:
            url = f"{nivel.url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {nivel.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self.PROBE_TIMEOUT) as client:
                r = await client.get(url, headers=headers)
                return r.status_code < 500
        except Exception:
            return False

    def _update(self, level: int, ok: bool, name: str) -> None:
        prev = self._health.get(level)   # None = primer sondeo

        if ok:
            self._fails[level] = 0
            self._oks[level] = self._oks.get(level, 0) + 1
            new_healthy = True
        else:
            self._oks[level] = 0
            fails = self._fails.get(level, 0) + 1
            self._fails[level] = fails
            if fails >= self.FAIL_THRESHOLD:
                new_healthy = False
            else:
                # Umbral no alcanzado: conserva estado previo
                new_healthy = prev if prev is not None else True

        self._health[level] = new_healthy

        # Logging de transiciones
        if prev is None:
            logger.info(
                "LLM Watchdog | L{} {} sondeo inicial → {}",
                level, name, "UP" if new_healthy else "DOWN",
            )
        elif new_healthy and not prev:
            logger.info("LLM Watchdog | L{} {} RECUPERADO ✓", level, name)
        elif not new_healthy and prev:
            logger.warning(
                "LLM Watchdog | L{} {} CAÍDO ✗ — el router usará el siguiente nivel disponible",
                level, name,
            )
