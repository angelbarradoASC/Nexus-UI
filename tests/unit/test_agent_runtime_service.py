from nexus.agents.shared import AgentRequest
from nexus.application.services.agent_runtime_service import AgentRuntimeService


def test_create_run_routes_operator_modes_to_operator():
    runtime = AgentRuntimeService()

    run = runtime.create_run(
        AgentRequest(
            message="revisa las alertas del cluster",
            source_surface="desktop",
            mode="operator",
        )
    )

    assert run.agent_id == "operator"
    assert run.source_surface == "desktop"
    assert run.metadata["resolved_agent_id"] == "operator"


def test_create_run_keeps_supervisor_for_general_requests():
    runtime = AgentRuntimeService()

    run = runtime.create_run(
        AgentRequest(
            message="quiero entender que agente deberia actuar",
            source_surface="web",
            mode="general",
        )
    )

    assert run.agent_id == "supervisor"
    assert run.metadata["resolved_agent_id"] == "supervisor"


def test_create_run_honours_explicit_target_agent():
    runtime = AgentRuntimeService()

    run = runtime.create_run(
        AgentRequest(
            message="recoge evidencias del host",
            source_surface="desktop",
            mode="general",
            target_agent_id="shell",
        )
    )

    assert run.agent_id == "shell"
    assert run.metadata["requested_agent_id"] == "shell"
