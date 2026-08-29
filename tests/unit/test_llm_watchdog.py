from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.llm_router import LLMLevel
from agents.llm_watchdog import LevelWatchdog, _extract_size_token


def _level(level, name, model, url="https://api.groq.com/openai/v1") -> LLMLevel:
    return LLMLevel(level=level, name=name, url=url, api_key="k", model=model)


def _fake_response(status_code: int, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=payload or {})
    return resp


def _patch_get(response_or_factory):
    """Parchea httpx.AsyncClient para que .get() devuelva la respuesta dada
    (o la calcule con response_or_factory(url) si es una funcion factory).

    OJO: no se puede distinguir "es invocable" con callable() porque un
    MagicMock() de respuesta tambien es invocable por defecto (bug real que
    piso este mismo test al escribirlo) — se distingue por si tiene
    status_code (= es una respuesta ya construida) en vez de por callable().
    """
    async def _get(url, headers=None):
        if hasattr(response_or_factory, "status_code"):
            return response_or_factory
        return response_or_factory(url)

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=_get)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    return patch("agents.llm_watchdog.httpx.AsyncClient", return_value=client_cm)


def test_extract_size_token():
    assert _extract_size_token("openai/gpt-oss-20b") == 20.0
    assert _extract_size_token("qwen/qwen3.8-27b") == 27.0
    assert _extract_size_token("groq/compound") is None


@pytest.mark.asyncio
async def test_probe_marks_level_up_when_model_present():
    levels = {1: _level(1, "L1", "openai/gpt-oss-20b")}
    wd = LevelWatchdog(levels)
    payload = {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "qwen/qwen3.8-27b"}]}
    with _patch_get(_fake_response(200, payload)):
        await wd._probe_all()
    assert wd.is_healthy(1) is True
    assert wd._model_missing.get(1) is False
    assert levels[1].model == "openai/gpt-oss-20b"  # sin swap


@pytest.mark.asyncio
async def test_dead_model_gets_swapped_in_memory_not_env():
    """Caso real: el modelo configurado ya no esta en el catalogo del
    proveedor (como paso con llama-3.3-70b-versatile en Groq) — el watchdog
    debe sustituirlo por un candidato vivo, sin tocar nada fuera de memoria.
    """
    levels = {2: _level(2, "L2", "llama-3.3-70b-versatile")}
    wd = LevelWatchdog(levels)
    payload = {"data": [{"id": "qwen/qwen3.8-27b"}, {"id": "openai/gpt-oss-120b"}]}
    with _patch_get(_fake_response(200, payload)):
        await wd._probe_all()

    assert wd._model_missing[2] is True
    assert levels[2].model in {"qwen/qwen3.8-27b", "openai/gpt-oss-120b"}
    assert levels[2].model != "llama-3.3-70b-versatile"
    # El nivel sigue considerandose sano — nunca se queda sin modelo.
    assert wd.is_healthy(2) is True


@pytest.mark.asyncio
async def test_replacement_prefers_closest_size():
    levels = {2: _level(2, "L2", "llama-3.3-70b-versatile")}
    wd = LevelWatchdog(levels)
    # 27b y 120b disponibles — 27b esta mas lejos de 70 que ninguno, pero
    # entre las dos, 120b (dist=50) esta mas cerca que 27b (dist=43)... se
    # comprueba explicitamente con tres opciones para no depender de un
    # empate ambiguo.
    payload = {"data": [
        {"id": "small/model-8b"}, {"id": "mid/model-72b"}, {"id": "big/model-200b"},
    ]}
    with _patch_get(_fake_response(200, payload)):
        await wd._probe_all()
    assert levels[2].model == "mid/model-72b"  # |72-70|=2, la mas cercana


@pytest.mark.asyncio
async def test_replacement_excludes_non_chat_models():
    levels = {1: _level(1, "L1", "dead-model-20b")}
    wd = LevelWatchdog(levels)
    payload = {"data": [
        {"id": "whisper-large-v3"}, {"id": "meta-llama/llama-prompt-guard-2-86m"},
        {"id": "real-chat-model-20b"},
    ]}
    with _patch_get(_fake_response(200, payload)):
        await wd._probe_all()
    assert levels[1].model == "real-chat-model-20b"


@pytest.mark.asyncio
async def test_no_valid_replacement_leaves_level_untouched_and_logs_error():
    levels = {1: _level(1, "L1", "dead-model-20b")}
    wd = LevelWatchdog(levels)
    payload = {"data": [{"id": "whisper-large-v3"}]}  # solo modelos no-chat
    with _patch_get(_fake_response(200, payload)):
        await wd._probe_all()
    assert levels[1].model == "dead-model-20b"  # no se toca sin candidato valido
    assert wd._model_missing[1] is True


@pytest.mark.asyncio
async def test_replacement_avoids_model_already_used_by_another_level():
    levels = {
        1: _level(1, "L1", "dead-model-20b"),
        2: _level(2, "L2", "shared-model-27b"),
    }
    wd = LevelWatchdog(levels)

    def _resp_for(url):
        return _fake_response(200, {"data": [{"id": "shared-model-27b"}, {"id": "other-model-27b"}]})

    with _patch_get(_resp_for):
        await wd._probe_all()
    # L1 debia coger "other-model-27b", no duplicar el que ya usa L2.
    assert levels[1].model == "other-model-27b"


@pytest.mark.asyncio
async def test_watchdog_mutates_the_same_dict_the_router_reads():
    """El router pasa su propio dict de niveles al watchdog — un swap debe
    verse de inmediato en el siguiente lookup del router (misma referencia).
    """
    router_levels = {2: _level(2, "L2", "llama-3.3-70b-versatile")}
    wd = LevelWatchdog(router_levels)
    payload = {"data": [{"id": "qwen/qwen3.8-27b"}]}
    with _patch_get(_fake_response(200, payload)):
        await wd._probe_all()
    # Simula lo que hace LLMRouter.call(): nivel = self._levels[lv_num]
    assert router_levels[2].model == "qwen/qwen3.8-27b"


@pytest.mark.asyncio
async def test_probe_401_keeps_level_up_without_model_validation():
    """401/403 = servidor vivo pero sin poder listar modelos (problema de
    auth) — no debe marcarse como modelo ausente, solo no se valida.
    """
    levels = {1: _level(1, "L1", "some-model")}
    wd = LevelWatchdog(levels)
    with _patch_get(_fake_response(401)):
        await wd._probe_all()
    assert wd.is_healthy(1) is True
    assert wd._model_missing.get(1, False) is False
    assert levels[1].model == "some-model"


@pytest.mark.asyncio
async def test_probe_5xx_marks_down_after_threshold():
    levels = {1: _level(1, "L1", "some-model")}
    wd = LevelWatchdog(levels)
    with _patch_get(_fake_response(500)):
        await wd._probe_all()
        await wd._probe_all()
    assert wd.is_healthy(1) is False
