"""Skill groups used by the operator agent."""

OPERATOR_SKILL_MAP = {
    "observability.read": [
        "observability.check_alerts",
        "observability.query_prometheus",
        "observability.open_grafana",
    ],
    "incident.response": [
        "incident.collect_context",
        "incident.propose_actions",
        "incident.create_ticket",
        "assets.crear_ticket_operador",
    ],
}
