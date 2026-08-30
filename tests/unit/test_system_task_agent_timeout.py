"""tests/unit/test_system_task_agent_timeout.py

Regresion: un usuario confirmo un rastreo de disco C: completo buscando PDFs
y PEPO murio a los 60s con "El script tardo demasiado (timeout)." sin ningun
resultado parcial ni indicacion de que estaba trabajando de verdad — el
timeout usado era el de diagnosticos ligeros (_run_powershell default=60s),
no uno pensado para tareas de I/O real ya confirmadas por el usuario.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from desktop.local_agents.system_task_agent import (
    _CONFIRMED_SCRIPT_TIMEOUT,
    PendingSystemTask,
    SystemTaskAgent,
)


@pytest.mark.asyncio
async def test_confirmed_script_uses_the_long_timeout_not_the_diagnostic_default(monkeypatch):
    agent = SystemTaskAgent(SimpleNamespace(), llm_router=None, store=None)
    pending = PendingSystemTask(task="busca PDFs", kind="run_script", script="Get-ChildItem C:\\")

    seen: dict[str, object] = {}

    def _fake_run_powershell(script, *, timeout=60.0, env=None):
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(cmd=script, timeout=timeout)

    monkeypatch.setattr(
        "desktop.local_agents.system_task_agent._run_powershell", _fake_run_powershell
    )

    result = await agent._run_script_and_record(pending)

    assert seen["timeout"] == _CONFIRMED_SCRIPT_TIMEOUT
    assert _CONFIRMED_SCRIPT_TIMEOUT > 60.0
    assert result["is_done"] is False
    assert "10 minutos" in result["error"]
    assert "acotarlo" in result["error"]
