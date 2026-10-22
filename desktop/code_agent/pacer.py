"""
desktop/code_agent/pacer.py
-------------------------------
Limitador de tokens por minuto del agente de codigo.

Un bucle de agente reenvia TODO el contexto en cada paso, asi que gasta tokens
mucho mas rapido que un chat. Verificado en vivo (2026-10-19): la cuenta de Groq
tiene 8.000 tokens/minuto y el agente recibia HTTP 429 en el segundo paso. En vez
de dejar que el proveedor nos rechace (y la tarea muera), el agente espera aqui
hasta que su ventana de 60 s tenga hueco. Es mas lento, pero termina — y si ni
esperando cabe dentro del tiempo maximo de la tarea, se rinde AL MOMENTO en vez
de dormir minutos para nada (visto en vivo: una tarea siguio 10 min en bucle).

`PacedRouter` envuelve al LLM router: estima los tokens de cada peticion, espera
al pacer y, si aun asi llega un 429, penaliza la ventana y reintenta.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("nexus.code_agent")

# Medido contra Groq el 2026-10-19: prompt+tools de 4,9k caracteres = 1.450 tokens (~3,4 car/token).
CHARS_PER_TOKEN = 3.3
_OUTPUT_ALLOWANCE_CAP = 300
_WINDOW_SECONDS = 60.0

DEADLINE_ERROR = "code_agent_deadline"


def estimate_request_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, max_tokens: int) -> int:
    """Estimacion ligeramente conservadora: caracteres/3,3 de mensajes+tools, mas un
    margen de salida (un cuarto de max_tokens, con tope: casi nunca se usa entera)."""
    chars = len(json.dumps(messages, ensure_ascii=False, default=str))
    if tools:
        chars += len(json.dumps(tools, ensure_ascii=False))
    return int(chars / CHARS_PER_TOKEN) + min(max_tokens // 4, _OUTPUT_ALLOWANCE_CAP)


class TokenPacer:
    def __init__(
        self,
        tokens_per_minute: int = 6500,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.tokens_per_minute = tokens_per_minute
        self.clock = clock
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    def penalize(self, seconds: float) -> None:
        """El proveedor nos rechazo: no se envia nada mas hasta que pase este tiempo."""
        self._blocked_until = max(self._blocked_until, self.clock() + seconds)

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= _WINDOW_SECONDS:
            self._events.popleft()

    def eta(self, tokens: int) -> float:
        """Segundos que habria que esperar ahora mismo para enviar `tokens` (sin reservar nada)."""
        tokens = min(tokens, self.tokens_per_minute)
        now = self.clock()
        self._prune(now)
        blocked = max(self._blocked_until - now, 0.0)
        used = sum(t for _, t in self._events)
        wait = 0.0
        if used + tokens > self.tokens_per_minute:
            freed = 0
            for moment, amount in self._events:
                freed += amount
                wait = max(moment + _WINDOW_SECONDS - now, 0.0)
                if used - freed + tokens <= self.tokens_per_minute:
                    break
        return max(blocked, wait)

    async def acquire(self, tokens: int) -> float:
        """Espera hasta que `tokens` quepan en la ventana de 60 s. Devuelve los
        segundos esperados. Una peticion mayor que todo el presupuesto se deja
        pasar sola (cuando la ventana esta vacia) en vez de bloquearse siempre."""
        tokens = min(tokens, self.tokens_per_minute)
        waited = 0.0
        async with self._lock:
            while True:
                now = self.clock()
                self._prune(now)
                used = sum(t for _, t in self._events)
                blocked = max(self._blocked_until - now, 0.0)
                if blocked <= 0 and used + tokens <= self.tokens_per_minute:
                    self._events.append((now, tokens))
                    return waited
                until_free = (self._events[0][0] + _WINDOW_SECONDS - now) if self._events else 0.0
                delay = max(blocked, until_free, 0.05)
                await self._sleep(delay)
                waited += delay


def _deadline_response() -> Any:
    return SimpleNamespace(error=DEADLINE_ERROR, content="", tool_calls=None)


class PacedRouter:
    """Mismo contrato que el LLM router (`call(...)`), pero respetando el pacer y,
    opcionalmente, un limite de tiempo para la tarea (`deadline_fn()` -> instante
    del reloj del pacer, o None)."""

    _RETRY_WAITS = (20.0, 45.0)

    def __init__(self, router: Any, pacer: TokenPacer, deadline_fn: Callable[[], float | None] | None = None) -> None:
        self._router = router
        self._pacer = pacer
        self._deadline_fn = deadline_fn

    def __getattr__(self, name: str) -> Any:  # cualquier otro atributo del router real
        return getattr(self._router, name)

    def _out_of_time(self, estimate: int) -> bool:
        deadline = self._deadline_fn() if self._deadline_fn else None
        return deadline is not None and self._pacer.clock() + self._pacer.eta(estimate) > deadline

    async def _bounded_call(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """La llamada al modelo no puede durar mas que lo que queda de tarea. Medido el 2026-10-22: una peticion al
        servidor se quedo colgada 24 minutos (sin CPU, conexion abierta) y el limite de la tarea (10 min), que solo se
        comprobaba ENTRE llamadas, no se aplico."""
        deadline = self._deadline_fn() if self._deadline_fn else None
        if deadline is None:
            return await self._router.call(messages=messages, **kwargs)
        remaining = deadline - self._pacer.clock()
        if remaining <= 0:
            return _deadline_response()
        try:
            return await asyncio.wait_for(self._router.call(messages=messages, **kwargs), timeout=remaining)
        except asyncio.TimeoutError:
            logger.warning("CodeAgent: la llamada al modelo no respondio dentro del tiempo de la tarea; se cancela")
            return _deadline_response()

    async def call(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        estimate = estimate_request_tokens(messages, kwargs.get("tools"), int(kwargs.get("max_tokens") or 0))
        if self._out_of_time(estimate):
            return _deadline_response()
        waited = await self._pacer.acquire(estimate)
        if waited >= 1:
            logger.info("CodeAgent esperó %.0fs para respetar la cuota de tokens/minuto (~%d tokens)", waited, estimate)

        response = await self._bounded_call(messages, **kwargs)
        for pause in self._RETRY_WAITS:
            if "429" not in str(getattr(response, "error", "") or ""):
                break
            logger.warning("CodeAgent: el proveedor devolvio 429; se espera %.0fs y se reintenta", pause)
            self._pacer.penalize(pause)
            if self._out_of_time(estimate):
                return _deadline_response()
            await self._pacer.acquire(estimate)
            response = await self._bounded_call(messages, **kwargs)
        return response
