from __future__ import annotations

from dataclasses import dataclass

from desktop.config import DesktopSettings
from desktop.opennexus.engine import OpenNexusEngine


@dataclass
class _FakeAssistantCore:
    async def execute(self, request):
        return type(
            "Resp",
            (),
            {
                "response": f"ok:{request.message}",
                "agent": "fake-agent",
                "status": "accepted",
                "flow": "chat",
                "audit_id": "audit-test",
                "resolution": request.resolution,
            },
        )()


@dataclass
class _FakeNexusRuntime:
    assistant_core: object


async def test_open_nexus_engine_executes_and_records_history(tmp_path):
    engine = OpenNexusEngine(
        settings=DesktopSettings(local_data_root=str(tmp_path)),
        nexus_runtime=_FakeNexusRuntime(assistant_core=_FakeAssistantCore()),
    )

    result = await engine.execute("diagnostica el servidor web-prod-01")

    assert result.response == "ok:diagnostica el servidor web-prod-01"
    assert result.resolution["skill_id"] == "ssh.diagnostico"
    assert len(engine.history) == 1


def test_open_nexus_snapshot_exposes_product_and_examples():
    engine = OpenNexusEngine(
        settings=DesktopSettings(),
        nexus_runtime=_FakeNexusRuntime(assistant_core=_FakeAssistantCore()),
    )

    snapshot = engine.snapshot()

    assert snapshot["product"]["name"] == "Open-Nexus"
    assert snapshot["product"]["inspired_by"] == "Open Interpreter"
    assert isinstance(snapshot["examples"], list)


async def test_open_nexus_engine_recovers_persisted_history(tmp_path):
    settings = DesktopSettings(local_data_root=str(tmp_path))

    engine_a = OpenNexusEngine(
        settings=settings,
        nexus_runtime=_FakeNexusRuntime(assistant_core=_FakeAssistantCore()),
    )
    await engine_a.execute("consulta el ticket NEXUS-42")

    engine_b = OpenNexusEngine(
        settings=settings,
        nexus_runtime=_FakeNexusRuntime(assistant_core=_FakeAssistantCore()),
    )

    assert len(engine_b.history) >= 1
    assert engine_b.history[0].user_input == "consulta el ticket NEXUS-42"
