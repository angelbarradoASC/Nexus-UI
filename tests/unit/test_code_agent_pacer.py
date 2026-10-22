"""tests/unit/test_code_agent_pacer.py

Limitador de tokens/minuto del agente de codigo. Bug real visto en vivo
(2026-10-19): la cuenta de Groq tiene 8.000 tokens/minuto y el bucle del agente
-que reenvia todo el contexto en cada paso- recibia HTTP 429 en el segundo paso.
Con el pacer el agente espera hueco en su ventana en vez de morir.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.code_agent.agent import CodeAgent
from desktop.code_agent.pacer import PacedRouter, TokenPacer, estimate_request_tokens


class _FakeClock:
    """Reloj y sleep falsos: dormir solo avanza el tiempo."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _pacer(budget: int = 1000) -> tuple[TokenPacer, _FakeClock]:
    clock = _FakeClock()
    return TokenPacer(budget, clock=clock, sleep=clock.sleep), clock


# ── TokenPacer ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_requests_within_the_budget_do_not_wait():
    pacer, clock = _pacer(1000)

    assert await pacer.acquire(400) == 0
    assert await pacer.acquire(500) == 0
    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_a_request_that_does_not_fit_waits_until_the_oldest_leaves_the_window():
    pacer, clock = _pacer(1000)
    await pacer.acquire(800)          # t=1000
    clock.now += 10                    # t=1010

    waited = await pacer.acquire(500)  # 800+500 > 1000: espera a que salga la primera (t=1060)

    assert waited == pytest.approx(50)
    assert clock.now == pytest.approx(1060)


@pytest.mark.asyncio
async def test_the_window_slides_and_old_usage_is_forgotten():
    pacer, clock = _pacer(1000)
    await pacer.acquire(900)
    clock.now += 61

    assert await pacer.acquire(900) == 0


@pytest.mark.asyncio
async def test_a_request_bigger_than_the_whole_budget_still_goes_through_alone():
    pacer, clock = _pacer(1000)

    assert await pacer.acquire(5000) == 0   # se recorta al presupuesto, no se bloquea para siempre
    waited = await pacer.acquire(100)       # ...pero llena la ventana: lo siguiente espera
    assert waited == pytest.approx(60)


@pytest.mark.asyncio
async def test_penalize_blocks_everything_until_it_expires():
    pacer, clock = _pacer(1000)
    pacer.penalize(30)

    waited = await pacer.acquire(10)

    assert waited == pytest.approx(30)


@pytest.mark.asyncio
async def test_eta_reports_the_wait_without_reserving_anything():
    pacer, clock = _pacer(1000)
    await pacer.acquire(800)
    clock.now += 10

    assert pacer.eta(100) == 0
    assert pacer.eta(500) == pytest.approx(50)
    assert pacer.eta(500) == pytest.approx(50)    # sin efectos: sigue igual
    pacer.penalize(80)
    assert pacer.eta(10) == pytest.approx(80)
    assert clock.sleeps == []


def test_estimate_grows_with_context_and_adds_an_output_allowance():
    small = estimate_request_tokens([{"role": "user", "content": "hola"}], None, 0)
    big = estimate_request_tokens([{"role": "user", "content": "x" * 3000}], None, 0)
    with_tools = estimate_request_tokens([{"role": "user", "content": "hola"}], [{"type": "function"}], 1200)

    assert big - small > 900
    assert 250 <= with_tools - small <= 320   # un cuarto de max_tokens, con tope


# ── PacedRouter ──────────────────────────────────────────────────────────────

class _Router:
    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.marker = "atributo del router real"

    async def call(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self._responses.pop(0)


def _ok(content="hecho"):
    return SimpleNamespace(error=None, content=content, tool_calls=None)


def _err(text):
    return SimpleNamespace(error=text, content="", tool_calls=None)


@pytest.mark.asyncio
async def test_paced_router_forwards_the_call_and_delegates_attributes():
    pacer, _ = _pacer(10_000)
    router = _Router(_ok())
    paced = PacedRouter(router, pacer)

    response = await paced.call([{"role": "user", "content": "hola"}], tools=[], max_tokens=100, preferred_level=2)

    assert response.content == "hecho"
    assert router.calls[0]["max_tokens"] == 100 and router.calls[0]["preferred_level"] == 2
    assert paced.marker == "atributo del router real"


@pytest.mark.asyncio
async def test_paced_router_waits_for_quota_before_calling():
    pacer, clock = _pacer(1000)
    router = _Router(_ok(), _ok())
    paced = PacedRouter(router, pacer)
    big = [{"role": "user", "content": "x" * 2400}]  # ~800 tokens estimados

    await paced.call(big, max_tokens=0)
    await paced.call(big, max_tokens=0)

    assert sum(clock.sleeps) == pytest.approx(60)   # la segunda espero a que saliera la primera


@pytest.mark.asyncio
async def test_paced_router_retries_a_429_after_penalising_and_then_succeeds():
    pacer, clock = _pacer(100_000)
    router = _Router(_err("http_429 | nivel=L3"), _ok("al segundo intento"))

    response = await PacedRouter(router, pacer).call([{"role": "user", "content": "hola"}])

    assert response.content == "al segundo intento"
    assert len(router.calls) == 2
    assert sum(clock.sleeps) >= 20


@pytest.mark.asyncio
async def test_paced_router_gives_up_after_two_retries_and_returns_the_error():
    pacer, _ = _pacer(100_000)
    router = _Router(_err("http_429"), _err("http_429"), _err("http_429"))

    response = await PacedRouter(router, pacer).call([{"role": "user", "content": "hola"}])

    assert "429" in response.error
    assert len(router.calls) == 3


@pytest.mark.asyncio
async def test_paced_router_gives_up_immediately_when_waiting_would_pass_the_deadline():
    """Visto en vivo: una tarea siguio 10 minutos durmiendo un minuto por paso para nada."""
    pacer, clock = _pacer(1000)
    router = _Router(_ok())
    await pacer.acquire(1000)                               # ventana llena: habria que esperar 60 s
    paced = PacedRouter(router, pacer, deadline_fn=lambda: clock.now + 30)   # solo quedan 30 s

    response = await paced.call([{"role": "user", "content": "hola"}], max_tokens=0)

    assert response.error == "code_agent_deadline"
    assert router.calls == [] and clock.sleeps == []         # ni llamo al proveedor ni durmio


@pytest.mark.asyncio
async def test_paced_router_waits_when_the_deadline_leaves_enough_time():
    pacer, clock = _pacer(1000)
    router = _Router(_ok())
    await pacer.acquire(1000)
    paced = PacedRouter(router, pacer, deadline_fn=lambda: clock.now + 600)

    response = await paced.call([{"role": "user", "content": "hola"}], max_tokens=0)

    assert response.content == "hecho" and sum(clock.sleeps) == pytest.approx(60)


@pytest.mark.asyncio
async def test_paced_router_does_not_retry_other_errors():
    pacer, _ = _pacer(100_000)
    router = _Router(_err("http_500"))

    response = await PacedRouter(router, pacer).call([{"role": "user", "content": "hola"}])

    assert response.error == "http_500"
    assert len(router.calls) == 1


# ── CodeAgent ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_explains_a_rate_limit_instead_of_showing_the_raw_error(tmp_path):
    from desktop.storage.code_settings import CodeSettingsStore

    project = tmp_path / "p"
    project.mkdir()
    settings = CodeSettingsStore(tmp_path / "s.json")
    settings.add_workspace(str(project))
    router = _Router(_err("http_429 | nivel=L3-Groq-GptOss120B"))
    agent = CodeAgent(None, llm_router=router, settings=settings)
    agent._llm_router._RETRY_WAITS = ()   # sin esperas reales en el test

    result = await agent.propose("ctx", "hola", workspace=str(project))

    assert result["kind"] == "finish"
    assert "limitado los tokens por minuto" in result["summary"]
    assert "http_429" not in result["summary"]


def test_agent_budget_is_below_the_provider_limit():
    assert CodeAgent.tokens_per_minute < 8000   # margen para el resto de PEPO, que comparte la cuenta
    assert CodeAgent.max_tokens <= 1500


@pytest.mark.asyncio
async def test_agent_applies_the_configured_quota_and_stops_when_out_of_time(tmp_path):
    from desktop.storage.code_settings import CodeSettingsStore

    project = tmp_path / "p"
    project.mkdir()
    settings = CodeSettingsStore(tmp_path / "s.json")
    settings.add_workspace(str(project))
    settings.set_tokens_per_minute(2000)           # cuota minima: cada paso cabe a duras penas
    router = _Router(*[SimpleNamespace(error=None, content="", tool_calls=[
        {"id": f"c{i}", "function": {"name": "list_directory", "arguments": "{}"}}]) for i in range(10)])
    agent = CodeAgent(None, llm_router=router, settings=settings)
    agent.max_task_seconds = 5.0                   # la tarea no tiene tiempo para esperar la cuota

    result = await agent.propose("ctx", "explora", workspace=str(project))

    assert agent._pacer.tokens_per_minute == 2000
    assert "quedado sin tiempo" in result["summary"]
    assert "2000 por minuto" in result["summary"]
    assert "code_agent_deadline" not in result["summary"]
    assert len(router.calls) <= 2                  # no sigue quemando llamadas


# ── Una llamada colgada no puede superar el limite de la tarea ───────────────

@pytest.mark.asyncio
async def test_a_hung_model_call_is_cancelled_at_the_task_deadline():
    """Visto en vivo (2026-10-22): una peticion al servidor se quedo colgada 24 minutos y el limite de 10 min, que solo
    se miraba entre llamadas, no se aplico."""
    import asyncio
    import time

    from desktop.code_agent.pacer import DEADLINE_ERROR

    class _Hangs:
        async def call(self, messages, **kwargs):
            await asyncio.sleep(30)

    pacer = TokenPacer(10**9)
    paced = PacedRouter(_Hangs(), pacer, deadline_fn=lambda: time.monotonic() + 0.2)

    started = time.monotonic()
    response = await paced.call([{"role": "user", "content": "hola"}])

    assert response.error == DEADLINE_ERROR
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_without_a_deadline_the_call_is_not_bounded():
    class _Slow:
        async def call(self, messages, **kwargs):
            return SimpleNamespace(error=None, content="ok", tool_calls=None)

    response = await PacedRouter(_Slow(), TokenPacer(10**9)).call([{"role": "user", "content": "hola"}])

    assert response.content == "ok"
