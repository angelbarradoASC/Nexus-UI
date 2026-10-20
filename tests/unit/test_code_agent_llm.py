"""tests/unit/test_code_agent_llm.py

Modelo propio del agente de codigo (Ollama) y recuperacion de tool calls en texto.
Medido el 2026-10-19: qwen2.5-coder (3B y 14B) devuelve la llamada a la herramienta
como TEXTO JSON, a veces dentro de ```json, en vez de `tool_calls`; Groq limita a
8.000 tokens/min y un modelo local no tiene ese limite.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desktop.code_agent import llm as llm_module
from desktop.code_agent.agent import CodeAgent
from desktop.code_agent.llm import (
    CodeLLM,
    OllamaToolClient,
    extract_text_tool_calls,
    recover_text_tool_calls,
)
from desktop.storage.code_settings import CodeSettingsStore
from products.desktop.backend import code_routes
from products.desktop.backend.code_routes import get_code_settings_store

NAMES = {"read_file", "grep", "list_directory", "finish"}
TOOLS = [{"type": "function", "function": {"name": n}} for n in sorted(NAMES)]


def _names(calls):
    return [c["function"]["name"] for c in calls]


# ── Recuperacion de tool calls en texto ──────────────────────────────────────

def test_raw_json_text_is_recovered_as_a_tool_call():
    calls = extract_text_tool_calls('{"name": "list_directory", "arguments": {"path": "."}}', NAMES)

    assert _names(calls) == ["list_directory"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "."}
    assert calls[0]["id"].startswith("call_") and calls[0]["type"] == "function"


def test_json_inside_a_markdown_fence_is_recovered():
    """Es exactamente lo que devolvio qwen2.5-coder:3b en el servidor."""
    text = '```json\n{\n  "name": "list_directory",\n  "arguments": {\n    "path": "."\n  }\n}\n```'

    assert _names(extract_text_tool_calls(text, NAMES)) == ["list_directory"]


def test_tool_call_tags_and_function_wrappers_and_string_arguments_are_recovered():
    tagged = '<tool_call>\n{"name": "grep", "arguments": {"pattern": "def "}}\n</tool_call>'
    wrapped = '{"function": {"name": "read_file", "arguments": "{\\"path\\": \\"a.py\\"}"}}'
    params = '{"name": "read_file", "parameters": {"path": "b.py"}}'

    assert _names(extract_text_tool_calls(tagged, NAMES)) == ["grep"]
    assert json.loads(extract_text_tool_calls(wrapped, NAMES)[0]["function"]["arguments"]) == {"path": "a.py"}
    assert json.loads(extract_text_tool_calls(params, NAMES)[0]["function"]["arguments"]) == {"path": "b.py"}


def test_a_list_of_calls_is_recovered_in_order():
    text = '[{"name": "read_file", "arguments": {"path": "a.py"}}, {"name": "read_file", "arguments": {"path": "b.py"}}]'

    calls = extract_text_tool_calls(text, NAMES)

    assert [json.loads(c["function"]["arguments"])["path"] for c in calls] == ["a.py", "b.py"]


@pytest.mark.parametrize("text", [
    '{"name": "rm_rf", "arguments": {"path": "/"}}',          # herramienta que no existe: nunca
    '{"name": "run_command", "arguments": {"command": "x"}}',  # tampoco una que el agente no tiene
    "Claro, voy a listar la carpeta.",                         # texto normal
    '{"respuesta": "hola", "n": 3}',                           # JSON que no es una llamada
    '{"name": "read_file", "arguments": "no es json"}',        # argumentos ilegibles
    '{"name": "read_file", "arguments": [1, 2]}',              # argumentos que no son objeto
    '{"name": "read_file", "arguments": {"path": ',            # JSON roto
    "",
])
def test_text_that_is_not_a_known_tool_call_is_never_converted(text):
    assert extract_text_tool_calls(text, NAMES) == []


def test_nothing_is_recovered_without_known_tools():
    assert extract_text_tool_calls('{"name": "read_file", "arguments": {}}', set()) == []


def test_recover_fills_tool_calls_and_clears_the_text():
    response = SimpleNamespace(error=None, content='{"name": "grep", "arguments": {"pattern": "x"}}', tool_calls=None)

    recover_text_tool_calls(response, TOOLS)

    assert _names(response.tool_calls) == ["grep"] and response.content == ""


def test_recover_leaves_errors_and_native_tool_calls_alone():
    native = SimpleNamespace(error=None, content='{"name": "grep", "arguments": {}}', tool_calls=[{"id": "x"}])
    failed = SimpleNamespace(error="http_500", content='{"name": "grep", "arguments": {}}', tool_calls=None)

    assert recover_text_tool_calls(native, TOOLS).tool_calls == [{"id": "x"}]
    assert recover_text_tool_calls(failed, TOOLS).tool_calls is None


# ── OllamaToolClient ─────────────────────────────────────────────────────────

def _ollama(handler, **kwargs) -> OllamaToolClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaToolClient("http://servidor:11434/", "qwen2.5-coder:3b", client=client, **kwargs)


@pytest.mark.asyncio
async def test_request_uses_native_chat_with_the_context_window_and_converts_messages():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hola"}})

    messages = [
        {"role": "system", "content": "sistema"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "grep", "arguments": '{"pattern": "x"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "resultado"},
    ]

    response = await _ollama(handler, num_ctx=16384).call(
        messages, tools=TOOLS, temperature=0.1, max_tokens=900, timeout=60
    )

    body = seen["body"]
    assert seen["url"] == "http://servidor:11434/api/chat"          # nativo, no /v1: solo asi se fija num_ctx
    assert body["model"] == "qwen2.5-coder:3b" and body["stream"] is False
    assert body["options"] == {"num_ctx": 16384, "temperature": 0.1, "num_predict": 900}
    assert body["think"] is False                                    # por defecto sin razonamiento
    assert body["tools"] == TOOLS
    assistant = body["messages"][1]
    assert assistant["content"] == "" and assistant["tool_calls"][0]["function"]["arguments"] == {"pattern": "x"}
    assert "id" not in assistant["tool_calls"][0]
    assert "tool_call_id" not in body["messages"][2]
    assert response.error is None and response.content == "hola" and response.tool_calls is None
    assert messages[1]["content"] is None                              # no se modifican los mensajes del agente


@pytest.mark.asyncio
async def test_native_tool_calls_come_back_in_openai_format():
    def handler(request):
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "a.py"}}}]}})

    response = await _ollama(handler).call([{"role": "user", "content": "x"}], tools=TOOLS)

    call = response.tool_calls[0]
    assert call["function"]["name"] == "read_file"
    assert json.loads(call["function"]["arguments"]) == {"path": "a.py"}
    assert call["id"]


@pytest.mark.asyncio
async def test_http_errors_and_network_failures_become_an_error_string():
    http_error = await _ollama(lambda r: httpx.Response(500, json={"error": "model 'x' not found"})).call(
        [{"role": "user", "content": "x"}])

    def boom(request):
        raise httpx.ConnectError("sin red")

    network = await _ollama(boom).call([{"role": "user", "content": "x"}])

    assert http_error.error.startswith("ollama_http_500") and "not found" in http_error.error
    assert network.error.startswith("ollama_error") and "ConnectError" in network.error


# ── CodeLLM ──────────────────────────────────────────────────────────────────

class _Settings:
    def __init__(self, own=None) -> None:
        self._own = own

    def llm(self):
        return self._own


class _Router:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def call(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.response


@pytest.mark.asyncio
async def test_code_llm_uses_the_router_when_no_own_model_is_configured_and_recovers_text_calls():
    router = _Router(SimpleNamespace(error=None, content='{"name": "grep", "arguments": {"pattern": "x"}}', tool_calls=None))

    response = await CodeLLM(router, _Settings()).call([{"role": "user", "content": "x"}], tools=TOOLS, max_tokens=100)

    assert _names(response.tool_calls) == ["grep"]
    assert router.calls[0]["max_tokens"] == 100


@pytest.mark.asyncio
async def test_code_llm_prefers_the_own_model_and_never_touches_the_router(monkeypatch):
    router = _Router(SimpleNamespace(error=None, content="router", tool_calls=None))
    used = {}

    async def fake_call(self, messages, **kwargs):
        used.update(url=self.base_url, model=self.model, num_ctx=self.num_ctx, think=self.think)
        return SimpleNamespace(error=None, content="propio", tool_calls=None)

    monkeypatch.setattr(OllamaToolClient, "call", fake_call)
    own = {"base_url": "http://servidor:11434", "model": "qwen2.5-coder:3b", "num_ctx": 8192, "think": True}

    response = await CodeLLM(router, _Settings(own)).call([{"role": "user", "content": "x"}])

    assert response.content == "propio" and router.calls == []
    assert used == {"url": "http://servidor:11434", "model": "qwen2.5-coder:3b", "num_ctx": 8192, "think": True}


@pytest.mark.asyncio
async def test_code_llm_without_model_or_router_explains_itself():
    response = await CodeLLM(None, _Settings()).call([{"role": "user", "content": "x"}])

    assert "no_llm" in response.error


# ── CodeAgent con modelo propio ──────────────────────────────────────────────

def _scripted(monkeypatch, *responses):
    queue = list(responses)
    seen: list[list[dict]] = []

    async def fake_call(self, messages, **kwargs):
        seen.append(json.loads(json.dumps(messages)))
        return queue.pop(0)

    monkeypatch.setattr(OllamaToolClient, "call", fake_call)
    return seen


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    (root / "app.py").write_text("def saluda():\n    return 'hola'\n", encoding="utf-8")
    settings = CodeSettingsStore(tmp_path / "s.json")
    settings.add_workspace(str(root))
    settings.set_llm("http://servidor:11434", "qwen2.5-coder:3b", 8192)
    return root, settings


@pytest.mark.asyncio
async def test_agent_runs_on_the_own_model_without_any_router_and_executes_recovered_text_calls(monkeypatch, project):
    root, settings = project
    seen = _scripted(
        monkeypatch,
        SimpleNamespace(error=None, tool_calls=None, content='```json\n{"name": "read_file", "arguments": {"path": "app.py"}}\n```'),
        SimpleNamespace(error=None, tool_calls=None, content='{"name": "finish", "arguments": {"summary": "saluda esta en app.py:1"}}'),
    )
    agent = CodeAgent(None, llm_router=None, settings=settings)      # sin router: solo el modelo propio

    result = await agent.propose("ctx", "¿donde esta saluda?", workspace=str(root))

    assert result == {"kind": "finish", "task": "¿donde esta saluda?", "summary": "saluda esta en app.py:1"}
    tool_message = [m for m in seen[1] if m["role"] == "tool"][0]
    assert "def saluda" in tool_message["content"]                    # la lectura se ejecuto de verdad


@pytest.mark.asyncio
async def test_own_model_is_not_throttled_by_the_token_quota(monkeypatch, project):
    root, settings = project
    monkeypatch.setattr(CodeAgent, "max_finish_reviews", 0)   # esta prueba solo mira el pacer
    settings.set_tokens_per_minute(1_000)                              # cuota minima: con router esperaria
    _scripted(monkeypatch, SimpleNamespace(error=None, tool_calls=None, content='{"name": "finish", "arguments": {"summary": "ok"}}'))
    agent = CodeAgent(None, llm_router=None, settings=settings)

    await agent.propose("ctx", "hola", workspace=str(root))

    assert agent._pacer.tokens_per_minute >= 10**9


def test_context_budget_follows_the_models_context_window(tmp_path):
    small = CodeSettingsStore(tmp_path / "a.json")
    small.set_llm("http://s:11434", "m", 4096)
    large = CodeSettingsStore(tmp_path / "b.json")
    large.set_llm("http://s:11434", "m", 32768)

    small_budget = CodeAgent(None, settings=small)._context_char_budget()
    large_budget = CodeAgent(None, settings=large)._context_char_budget()

    assert small_budget < large_budget
    assert (small_budget + 3_100) / 3.3 < 4096          # mensajes + esquemas caben en num_ctx: nada se trunca en silencio


@pytest.mark.asyncio
async def test_agent_explains_a_local_model_failure(monkeypatch, project):
    root, settings = project
    _scripted(monkeypatch, SimpleNamespace(error="ollama_error | ConnectError: sin red", tool_calls=None, content=""))
    agent = CodeAgent(None, llm_router=None, settings=settings)

    result = await agent.propose("ctx", "hola", workspace=str(root))

    assert "modelo local" in result["summary"] and "Probar" in result["summary"]


@pytest.mark.asyncio
async def test_agent_still_refuses_when_there_is_neither_router_nor_own_model(tmp_path):
    settings = CodeSettingsStore(tmp_path / "s.json")
    root = tmp_path / "p"
    root.mkdir()
    settings.add_workspace(str(root))

    result = await CodeAgent(None, llm_router=None, settings=settings).propose("ctx", "hola", workspace=str(root))

    assert "no esta disponible" in result["summary"]


# ── Ajustes y API ────────────────────────────────────────────────────────────

def test_settings_own_model_roundtrip_validation_and_clearing(tmp_path):
    store = CodeSettingsStore(tmp_path / "s.json")
    assert store.llm() is None

    store.set_llm("http://192.168.68.150:11434/", "qwen2.5-coder:3b", 16384)
    assert store.llm() == {"base_url": "http://192.168.68.150:11434", "model": "qwen2.5-coder:3b", "num_ctx": 16384, "think": False}
    store.set_llm("http://192.168.68.150:11434", "qwen3:8b", 8192, think=True)
    assert store.llm()["think"] is True

    store.set_llm("http://x:1", "m", 10)                       # num_ctx se acota
    assert store.llm()["num_ctx"] == 2048
    for bad_url in ("192.168.68.150:11434", "ftp://x", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            store.set_llm(bad_url, "m")
    with pytest.raises(ValueError):
        store.set_llm("http://x:1", "")

    store.set_llm("", "")
    assert store.llm() is None


def _client(tmp_path):
    store = CodeSettingsStore(tmp_path / "s.json")
    app = FastAPI()
    app.include_router(code_routes.router)
    app.dependency_overrides[get_code_settings_store] = lambda: store
    return TestClient(app), store


def test_api_sets_validates_and_clears_the_model(tmp_path):
    client, store = _client(tmp_path)

    ok = client.put("/api/desktop/code/model", json={"base_url": "http://s:11434", "model": "qwen2.5-coder:3b", "num_ctx": 8192})
    assert ok.status_code == 200 and ok.json()["llm"]["model"] == "qwen2.5-coder:3b"
    assert store.llm() is not None

    assert client.put("/api/desktop/code/model", json={"base_url": "s:11434", "model": "m"}).status_code == 422
    assert client.put("/api/desktop/code/model", json={"base_url": "http://s", "model": ""}).status_code == 422
    assert client.put("/api/desktop/code/model", json={"base_url": "http://s", "model": "m", "num_ctx": 5}).status_code == 422
    assert store.llm()["base_url"] == "http://s:11434"           # los intentos invalidos no cambian nada

    cleared = client.put("/api/desktop/code/model", json={"base_url": "", "model": ""})
    assert cleared.json()["llm"]["model"] == "" and store.llm() is None


def test_api_connection_test_reports_each_situation(tmp_path, monkeypatch):
    client, store = _client(tmp_path)
    assert client.post("/api/desktop/code/model/test").json()["ok"] is False        # nada configurado

    store.set_llm("http://s:11434", "qwen2.5-coder:3b")
    monkeypatch.setattr(code_routes.httpx, "get", lambda *a, **k: httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:3b"}]}))
    assert client.post("/api/desktop/code/model/test").json()["ok"] is True

    monkeypatch.setattr(code_routes.httpx, "get", lambda *a, **k: httpx.Response(200, json={"models": [{"name": "otro:1b"}]}))
    missing = client.post("/api/desktop/code/model/test").json()
    assert missing["ok"] is False and "no esta descargado" in missing["detail"] and missing["available"] == ["otro:1b"]

    def down(*a, **k):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(code_routes.httpx, "get", down)
    assert "No responde" in client.post("/api/desktop/code/model/test").json()["detail"]


# ── Razonamiento (think) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_is_sent_as_configured_and_omitted_when_none():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    await _ollama(handler, think=True).call([{"role": "user", "content": "x"}])
    await _ollama(handler, think=None).call([{"role": "user", "content": "x"}])

    assert bodies[0]["think"] is True and "think" not in bodies[1]


@pytest.mark.asyncio
async def test_a_model_without_reasoning_mode_is_retried_without_the_parameter():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "think" in body:
            return httpx.Response(400, json={"error": "\"qwen2.5-coder:3b\" does not support thinking"})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hecho"}})

    response = await _ollama(handler, think=False).call([{"role": "user", "content": "x"}])

    assert response.error is None and response.content == "hecho"
    assert len(bodies) == 2 and "think" not in bodies[1]


@pytest.mark.asyncio
async def test_inline_think_blocks_are_removed_from_the_answer():
    def handler(request):
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "<think>\nrazono...\n</think>\nLa respuesta."}})

    response = await _ollama(handler, think=True).call([{"role": "user", "content": "x"}])

    assert response.content == "La respuesta."


def test_api_accepts_the_think_flag(tmp_path):
    client, store = _client(tmp_path)

    ok = client.put("/api/desktop/code/model", json={"base_url": "http://s:11434", "model": "qwen3:8b", "think": True})

    assert ok.status_code == 200 and ok.json()["llm"]["think"] is True
    assert store.llm()["think"] is True
