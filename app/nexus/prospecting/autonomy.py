"""Autonomous agent tracing helpers for Nexus Sales prospecting."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from nexus.prospecting.models import ProspectingBrief


AUTONOMOUS_AGENT_SPECS: list[dict[str, Any]] = [
    {
        "agent_id": "brief_guardian",
        "title": "Brief Guardian",
        "kind": "guardrail",
        "purpose": "Protege la intencion original y detecta huecos o contradicciones del briefing.",
    },
    {
        "agent_id": "brief_refiner",
        "title": "Brief Refiner",
        "kind": "planner",
        "purpose": "Refina criterios comerciales sin tocar geografia, vertical ni marca.",
    },
    {
        "agent_id": "source_strategist",
        "title": "Source Strategist",
        "kind": "planner",
        "purpose": "Decide el orden y el papel de cada fuente de descubrimiento.",
    },
    {
        "agent_id": "query_architect",
        "title": "Query Architect",
        "kind": "planner",
        "purpose": "Construye queries de baja friccion y poco ruido para la prospeccion.",
    },
    {
        "agent_id": "search_executor",
        "title": "Search Executor",
        "kind": "execution",
        "purpose": "Ejecuta la busqueda real contra Brave y/o Google Places.",
    },
    {
        "agent_id": "candidate_qualifier",
        "title": "Candidate Qualifier",
        "kind": "qualification",
        "purpose": "Extrae, valida y puntua candidatos antes de aceptarlos.",
    },
    {
        "agent_id": "crm_packager",
        "title": "CRM Packager",
        "kind": "handoff",
        "purpose": "Deja cada lead listo para CRM con tags, readiness y siguiente paso.",
    },
]

DEFAULT_GUARDRAILS: list[str] = [
    "No cambiar vertical, ciudad, provincia ni marca salvo error muy obvio.",
    "No inventar datos geograficos ni contacto directo inexistente.",
    "No reducir ni inflar desired_count sin evidencia.",
    "Evitar directorios, agregadores, marketplaces y ruido comercial cuando sea seguro.",
    "Ser conservador con official_website, contacto_person y contact_role.",
    "Solo preparar CRM con evidencia minima usable y trazable.",
]


class SalesAutonomousSystem:
    """Build and update the autonomous prospecting trace shared by Sales."""

    def bootstrap(self, brief: ProspectingBrief) -> dict[str, Any]:
        return {
            "system_id": "sales-autonomous-prospecting-v1",
            "status": "planned",
            "guardrails": list(DEFAULT_GUARDRAILS),
            "brief_snapshot": brief.to_dict(),
            "agent_count": len(AUTONOMOUS_AGENT_SPECS),
            "agents": [
                {
                    **spec,
                    "status": "pending",
                    "summary": "",
                    "warnings": [],
                    "guardrails_applied": [],
                    "inputs": {},
                    "outputs": {},
                }
                for spec in AUTONOMOUS_AGENT_SPECS
            ],
        }

    def clone(self, orchestration: dict[str, Any] | None, brief: ProspectingBrief) -> dict[str, Any]:
        if orchestration:
            return deepcopy(orchestration)
        return self.bootstrap(brief)

    def update_agent(
        self,
        orchestration: dict[str, Any] | None,
        *,
        brief: ProspectingBrief,
        agent_id: str,
        status: str,
        summary: str,
        warnings: list[str] | None = None,
        guardrails_applied: list[str] | None = None,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.clone(orchestration, brief)
        for agent in payload["agents"]:
            if agent["agent_id"] != agent_id:
                continue
            agent["status"] = status
            agent["summary"] = summary.strip()
            agent["warnings"] = self._clean_list(warnings)
            agent["guardrails_applied"] = self._clean_list(guardrails_applied)
            agent["inputs"] = inputs or {}
            agent["outputs"] = outputs or {}
            break
        payload["status"] = self._derive_status(payload["agents"])
        return payload

    def snapshot(self, orchestration: dict[str, Any] | None) -> dict[str, Any]:
        payload = deepcopy(orchestration or {})
        agents = payload.get("agents") or []
        payload["status"] = self._derive_status(agents)
        payload["agent_count"] = len(agents)
        payload["completed_agents"] = len([item for item in agents if item.get("status") == "completed"])
        payload["warning_agents"] = len([item for item in agents if item.get("warnings")])
        return payload

    @staticmethod
    def _derive_status(agents: list[dict[str, Any]]) -> str:
        statuses = [item.get("status") for item in agents]
        if any(status == "failed" for status in statuses):
            return "failed"
        if any(status == "running" for status in statuses):
            return "running"
        if statuses and all(status == "completed" for status in statuses):
            return "completed"
        if any(status == "completed" for status in statuses):
            return "partial"
        return "planned"

    @staticmethod
    def _clean_list(values: list[str] | None) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            cleaned = str(value or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
        return result[:8]
