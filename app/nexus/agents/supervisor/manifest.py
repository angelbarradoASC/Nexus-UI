"""Manifest for the Nexus supervisor agent."""

from nexus.agents.shared.result import AgentCapability, AgentManifest

SUPERVISOR_MANIFEST = AgentManifest(
    agent_id="supervisor",
    name="Nexus Supervisor",
    role="supervisor",
    description="Orquesta planes, enruta entre agentes y explica por que se toma cada decision.",
    accepted_modes=["general", "monitoring", "incident", "operator", "shell", "sales"],
    capabilities=[
        AgentCapability(
            capability_id="route.request",
            name="Routing",
            description="Selecciona el agente adecuado segun intencion, contexto y riesgo.",
        ),
        AgentCapability(
            capability_id="explain.plan",
            name="Explicacion",
            description="Devuelve plan, rationale y pasos visibles para el usuario.",
        ),
    ],
    skill_ids=["planning.route", "planning.explain"],
    connector_ids=[],
    tags=["always-on", "planner", "cross-surface"],
)
