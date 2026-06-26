from nexus.agents import get_default_agent_registry
from nexus.agents.shared import AgentExecutionContext, AgentRequest


def test_default_agent_registry_exposes_cross_surface_roles():
    registry = get_default_agent_registry()

    manifests = registry.list_manifests()
    agent_ids = {manifest.agent_id for manifest in manifests}

    assert {"supervisor", "operator", "shell", "sales"}.issubset(agent_ids)
    assert all(manifest.server_resident is True for manifest in manifests)
    assert all("desktop" in manifest.supported_surfaces for manifest in manifests)
    assert all("web" in manifest.supported_surfaces for manifest in manifests)


def test_operator_agent_bootstrap_run_uses_shared_contract():
    registry = get_default_agent_registry()
    operator = registry.get("operator")

    request = AgentRequest(
        message="Revisa las alarmas activas",
        user_id="tester",
        source_surface="desktop",
        mode="operator",
    )
    context = AgentExecutionContext(
        request_id="req-001",
        user_id="tester",
        source_surface="desktop",
    )

    run = operator.bootstrap_run(request, context)

    assert run.agent_id == "operator"
    assert run.source_surface == "desktop"
    assert run.status == "planned"
    assert len(run.plan_steps) == 3
    assert run.skill_calls[0].connector_id == "alertmanager"
