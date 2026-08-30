"""tests/unit/test_system_task_agent_file_tools.py

Cubre list_directory/read_file — las herramientas nuevas de SystemTaskAgent
para que PEPO pueda explorar/leer una carpeta real de este PC y analizar
codigo, en vez de responder "no puedo acceder al sistema de archivos"
(bug real reportado: PEPO se negaba a analizar codigo aunque el mismo
agente ya tiene acceso real al PC via run_script/run_diagnostic).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.system_task_agent import SystemTaskAgent


class _FakeLLMResponse:
    def __init__(self, *, tool_calls=None, content=None, error=None):
        self.tool_calls = tool_calls
        self.content = content
        self.error = error


def _tool_call(call_id: str, tool_name: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": tool_name, "arguments": json.dumps(arguments)}}


class _FakeLLMRouter:
    def __init__(self, responses: list[_FakeLLMResponse]):
        self._responses = list(responses)

    async def call(self, **kwargs):
        return self._responses.pop(0)


def _agent() -> SystemTaskAgent:
    return SystemTaskAgent(SimpleNamespace(), llm_router=None, store=None)


# ── list_directory (sync helper) ────────────────────────────────────────────

def test_list_directory_shows_dirs_and_files_sorted(tmp_path):
    (tmp_path / "b_file.py").write_text("x", encoding="utf-8")
    (tmp_path / "a_dir").mkdir()
    (tmp_path / "c_file.txt").write_text("y", encoding="utf-8")

    result = _agent()._list_directory_sync(str(tmp_path))

    lines = result.splitlines()
    assert "[DIR]  a_dir" in lines
    assert any(line.startswith("[FILE] b_file.py") for line in lines)
    assert any(line.startswith("[FILE] c_file.txt") for line in lines)
    # Directorios antes que ficheros
    assert lines.index("[DIR]  a_dir") < next(i for i, l in enumerate(lines) if l.startswith("[FILE]"))


def test_list_directory_missing_path_returns_clear_message(tmp_path):
    missing = tmp_path / "no-existe"
    result = _agent()._list_directory_sync(str(missing))
    assert "No existe la carpeta" in result


def test_list_directory_on_a_file_returns_clear_message(tmp_path):
    f = tmp_path / "archivo.txt"
    f.write_text("hola", encoding="utf-8")
    result = _agent()._list_directory_sync(str(f))
    assert "No es una carpeta" in result


def test_list_directory_truncates_very_large_directories(tmp_path):
    agent = _agent()
    agent._MAX_LIST_ENTRIES = 5
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    result = agent._list_directory_sync(str(tmp_path))
    assert "elementos mas, no mostrados" in result


# ── read_file (sync helper) ─────────────────────────────────────────────────

def test_read_file_returns_content(tmp_path):
    f = tmp_path / "main.py"
    f.write_text("print('hola mundo')", encoding="utf-8")
    result = _agent()._read_file_sync(str(f))
    assert "print('hola mundo')" in result
    assert str(f) in result


def test_read_file_missing_path_returns_clear_message(tmp_path):
    missing = tmp_path / "no-existe.py"
    result = _agent()._read_file_sync(str(missing))
    assert "No existe el fichero" in result


def test_read_file_on_a_directory_returns_clear_message(tmp_path):
    result = _agent()._read_file_sync(str(tmp_path))
    assert "No es un fichero" in result


def test_read_file_refuses_binary_content(tmp_path):
    f = tmp_path / "binario.bin"
    f.write_bytes(b"\x00\x01\x02\xff\xfe")
    result = _agent()._read_file_sync(str(f))
    assert "binario" in result.lower()


def test_read_file_truncates_when_too_large(tmp_path):
    agent = _agent()
    agent._MAX_READ_CHARS = 100
    f = tmp_path / "grande.py"
    f.write_text("a" * 500, encoding="utf-8")
    result = agent._read_file_sync(str(f))
    assert "truncado" in result
    assert result.count("a") <= 100 + 20  # margen por la cabecera del mensaje


# ── Bucle completo: list_directory -> read_file -> finish ──────────────────

@pytest.mark.asyncio
async def test_loop_lists_directory_then_reads_file_then_finishes(tmp_path):
    (tmp_path / "main.py").write_text("def f(): pass", encoding="utf-8")

    router = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("1", "list_directory", path=str(tmp_path))]),
        _FakeLLMResponse(tool_calls=[_tool_call("2", "read_file", path=str(tmp_path / "main.py"))]),
        _FakeLLMResponse(tool_calls=[_tool_call("3", "finish", summary="El proyecto tiene una funcion f() vacia.")]),
    ])
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=router, store=None)

    result = await agent.propose("ctx-1", f"analiza el codigo de {tmp_path}")

    assert result["kind"] == "finish"
    assert "funcion f()" in result["summary"]
