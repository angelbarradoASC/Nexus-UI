"""
app/agents/llm_watchdog.py
---------------------------
Watchdog proactivo para los niveles del LLM Router.

Sondea cada nivel con un GET ligero (sin gastar tokens) antes de que llegue
la primera llamada real. Mantiene un mapa de salud que el router consume en
_candidatos() para saltar directamente al primer nivel vivo.

Además del sondeo de "¿responde el proveedor?", valida que el MODELO
configurado siga existiendo en el catálogo que devuelve el proveedor
(/models, o /api/tags en Ollama). Un proveedor puede responder 200 perfectamente
y aun así el modelo llevar semanas retirado (caso real: Groq retiró toda la
familia Llama y el router llevaba toda la sesión cayendo en silencio a L3
sin que nadie lo supiera, porque el sondeo antiguo solo miraba el status
code). Si el modelo configurado desaparece del catálogo, se sustituye EN
MEMORIA por un candidato vivo del mismo proveedor — nunca se escribe en
.env, solo se avisa fuerte en logs para que un humano decida si lo hace
permanente.

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
import re
import time
from typing import Any

import httpx
from loguru import logger

# Modelos que aparecen en /models pero no son de chat completions — nunca
# elegibles como reemplazo automático (audio, guardrails, embeddings...).
_NON_CHAT_HINTS = ("whisper", "guard", "embed", "moderation", "tts", "orpheus")

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b")


def _extract_size_token(model_id: str) -> float | None:
    """Extrae el tamaño en B de un id de modelo (ej. 'gpt-oss-20b' → 20.0)."""
    match = _SIZE_RE.search(model_id.lower())
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


class LevelWatchdog:
    """Sondeo periódico y no bloqueante de la disponibilidad de cada nivel LLM."""

    PROBE_TIMEOUT     = 4.0   # segundos por intento
    FAIL_THRESHOLD    = 2     # fallos consecutivos para declarar DOWN
    RECOVER_THRESHOLD = 1     # éxitos consecutivos para declarar UP desde DOWN
    INTERVAL_HEALTHY  = 30    # segundos entre sondeos cuando todo está UP
    INTERVAL_DEGRADED = 10    # segundos entre sondeos cuando hay algún nivel DOWN

    def __init__(self, levels: dict[int, Any]) -> None:
        # levels: dict[int, LLMLevel] — aceptamos Any para evitar importación circular.
        # Se guarda la MISMA referencia de dict que usa LLMRouter — sustituir una
        # entrada aqui (tras un auto-swap de modelo) lo ve el router al instante.
        self._levels = levels
        self._health: dict[int, bool] = {}           # None-ausente = optimista
        self._fails:  dict[int, int]  = {}
        self._oks:    dict[int, int]  = {}
        self._last_ts: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}  # monotonic timestamp de fin de cooldown
        self._task: asyncio.Task[None] | None = None

        # ── Validacion de modelo (no solo de endpoint) ──
        self._configured_model: dict[int, str] = {lv: nivel.model for lv, nivel in levels.items()}
        self._model_missing: dict[int, bool] = {}
        self._tried_models: dict[int, set[str]] = {}

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
                "model":             nivel.model,
                "configured_model":  self._configured_model.get(lv, nivel.model),
                "model_missing":     self._model_missing.get(lv, False),
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
        for lv in list(self._levels.keys()):
            nivel = self._levels[lv]
            ok, available_models = await self._probe(nivel)
            self._last_ts[lv] = time.monotonic()
            self._update(lv, ok, nivel.name)
            if ok and available_models is not None:
                # nivel puede haber cambiado de objeto si _check_model ya
                # hizo un swap en una vuelta anterior — releer del dict.
                self._check_model(lv, self._levels[lv], available_models)

    async def _probe(self, nivel: Any) -> tuple[bool, set[str] | None]:
        """
        GET ligero al endpoint de listado del proveedor — no gasta tokens.
        Ollama:  GET /api/tags
        OpenAI-compatible: GET /models
        401/403 se consideran UP (servidor vivo, problema de auth) pero sin
        lista de modelos fiable (no se puede validar el modelo configurado).

        Returns:
            (endpoint_vivo, ids_de_modelo_disponibles_o_None)
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
                if r.status_code >= 500:
                    return False, None
                if r.status_code >= 400:
                    return True, None  # vivo, pero no autorizado a listar modelos
                return True, self._parse_model_ids(r, is_ollama=is_ollama)
        except Exception:
            return False, None

    @staticmethod
    def _parse_model_ids(response: httpx.Response, *, is_ollama: bool) -> set[str] | None:
        try:
            data = response.json()
        except Exception:
            return None
        try:
            if is_ollama:
                return {str(m["name"]) for m in data.get("models", []) if m.get("name")}
            return {str(m["id"]) for m in data.get("data", []) if m.get("id")}
        except Exception:
            return None

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

    # ── Validacion + auto-swap de modelo ────────────────────────────────────

    def _check_model(self, level: int, nivel: Any, available: set[str]) -> None:
        if nivel.model in available:
            if self._model_missing.get(level):
                logger.info(
                    "LLM Watchdog | L{} {} — el modelo '{}' vuelve a estar disponible",
                    level, nivel.name, nivel.model,
                )
            self._model_missing[level] = False
            return

        self._model_missing[level] = True
        replacement = self._pick_replacement(level, available)
        if replacement is None:
            logger.error(
                "LLM Watchdog | L{} {} — el modelo '{}' ya no existe en el catalogo del "
                "proveedor y no hay ningun candidato de chat disponible para sustituirlo. "
                "Este nivel se queda sin modelo funcional hasta que se arregle a mano.",
                level, nivel.name, nivel.model,
            )
            return

        self._tried_models.setdefault(level, set()).add(nivel.model)
        updated = nivel.model_copy(update={"model": replacement})
        self._levels[level] = updated
        logger.warning(
            "LLM Watchdog | L{} {} — el modelo configurado '{}' ya no existe en el proveedor "
            "(retirado o renombrado). Sustituido EN MEMORIA por '{}' para no perder este nivel "
            "— esto NO se ha escrito en .env, revisa y actualiza la configuracion cuando puedas.",
            level, nivel.name, self._configured_model.get(level, nivel.model), replacement,
        )

    def _pick_replacement(self, level: int, available: set[str]) -> str | None:
        tried = self._tried_models.get(level, set())
        candidates = {
            model_id for model_id in available
            if model_id not in tried and not any(hint in model_id.lower() for hint in _NON_CHAT_HINTS)
        }
        if not candidates:
            return None

        # Preferir un modelo que ningun otro nivel este usando ya, para que la
        # escalada L1→L2→L3 siga teniendo sentido (proveedores/tamaños distintos)
        # en vez de que dos niveles acaben siendo el mismo modelo por accidente.
        used_elsewhere = {other.model for lv, other in self._levels.items() if lv != level}
        pool = (candidates - used_elsewhere) or candidates

        target_size = _extract_size_token(self._configured_model.get(level, ""))
        if target_size is not None:
            sized = [(model_id, _extract_size_token(model_id)) for model_id in pool]
            sized = [(model_id, size) for model_id, size in sized if size is not None]
            if sized:
                best_id, _ = min(sized, key=lambda pair: abs(pair[1] - target_size))
                return best_id

        return sorted(pool)[0]
