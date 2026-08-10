from __future__ import annotations

from dataclasses import dataclass

from nexus.application.services.assistant_runtime_core import (
    AssistantExecutionRequest,
    AssistantRuntimeCore,
)


@dataclass
class _FakeCoordinator:
    captured_resolution: dict | None = None
    captured_history: list | None = None

    async def handle_chat(self, payload, *, resolution_override=None, history=None):
        # AssistantRuntimeCore.execute() siempre llama con resolution_override
        # Y history — sin el parametro history aqui, la llamada real lanza
        # TypeError, que execute() atrapa (ve "history" en el mensaje) y
        # reintenta SIN resolution_override, perdiendo la resolucion pasada.
        self.captured_resolution = resolution_override
        self.captured_history = history
        return type(
            "Resp",
            (),
            {
                "status": "accepted",
                "response": f"ok:{payload.message}",
                "agent": "fake-agent",
                "flow": "chat",
                "audit_id": "audit-123",
            },
        )()


async def test_assistant_runtime_core_uses_supplied_resolution():
    coordinator = _FakeCoordinator()
    core = AssistantRuntimeCore(coordinator)
    resolution = {
        "skill_id": "general.respuesta",
        "confidence": 0.5,
        "entities": {},
        "execution_mode": "assist",
    }

    result = await core.execute(
        AssistantExecutionRequest(
            message="hola",
            user_id="tester",
            source_surface="desktop",
            resolution=resolution,
        )
    )

    assert coordinator.captured_resolution == resolution
    assert result.response == "ok:hola"
    assert result.source_surface == "desktop"
