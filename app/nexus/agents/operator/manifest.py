"""Manifest for the operator agent."""

from nexus.agents.operator.skills_map import OPERATOR_SKILL_MAP
from nexus.agents.shared.result import AgentCapability, AgentManifest

OPERATOR_MANIFEST = AgentManifest(
    agent_id="operator",
    name="Nexus Operator",
    role="operator",
    description="Gestiona alarmas, metricas, incidentes y diagnostico operativo con trazabilidad.",
    accepted_modes=["monitoring", "incident", "operator"],
    capabilities=[
        AgentCapability(
            capability_id="observability.diagnose",
            name="Diagnostico operativo",
            description="Cruza Prometheus, Grafana y Alertmanager para explicar estados.",
        ),
        AgentCapability(
            capability_id="incident.manage",
            name="Gestion de incidentes",
            description="Propone acciones, runbooks y escalado con aprobacion cuando haga falta.",
        ),
    ],
    skill_ids=[skill for group in OPERATOR_SKILL_MAP.values() for skill in group],
    connector_ids=["prometheus", "grafana", "alertmanager"],
    tags=["always-on", "noc", "observability"],
)
