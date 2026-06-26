from __future__ import annotations

from nexus.investigation.technology_plan import TechnologyInvestigationPlanner
from nexus.targets.classifier import TechnologyResolution


def test_planner_construye_plan_linux():
    planner = TechnologyInvestigationPlanner()
    resolution = TechnologyResolution(
        technology_key="compute.linux",
        confidence=0.9,
        rationale="linux",
        target_hint="web-prod-01",
        access_key="ssh",
        capabilities=["host.run_command"],
    )

    plan = planner.build(resolution, user_message="alarma linux en web-prod-01")

    assert plan["technology_key"] == "compute.linux"
    assert plan["access"]["key"] == "ssh"
    assert any("carga" in step.lower() or "logs" in step.lower() for step in plan["steps"])


def test_planner_construye_plan_fortinet():
    planner = TechnologyInvestigationPlanner()
    resolution = TechnologyResolution(
        technology_key="network.firewall.fortinet",
        confidence=0.9,
        rationale="fortinet",
        target_hint="fw-core-01",
        access_key="fortios-api",
        capabilities=["firewall.system_status"],
    )

    plan = planner.build(resolution, user_message="alarma fortinet en fw-core-01")

    assert plan["technology_key"] == "network.firewall.fortinet"
    assert plan["risk_posture"] == "high_control"
    assert any("politic" in step.lower() or "sesion" in step.lower() for step in plan["steps"])
