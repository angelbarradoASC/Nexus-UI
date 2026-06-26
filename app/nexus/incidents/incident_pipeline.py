"""Incident lifecycle pipeline."""

from __future__ import annotations

import uuid

from nexus.domain.entities.incident import Incident
from nexus.api.schemas.incidents import IncidentIngestRequest, IncidentResponse
from nexus.domain.policies.risk import classify_severity


class IncidentPipeline:
    """Normalize incident intake and decide the immediate next step."""

    async def process(
        self,
        payload: IncidentIngestRequest,
        *,
        runbook: dict | None = None,
        ticket: dict | None = None,
    ) -> tuple[Incident, IncidentResponse]:
        severity = classify_severity(payload.severity)
        incident_id = payload.fingerprint or f"inc-{uuid.uuid4().hex[:12]}"
        next_action = "auto_diagnose" if severity == "critical" else "triage"
        incident = Incident(
            incident_id=incident_id,
            title=payload.title,
            severity=severity,
            source=payload.source,
            next_action=next_action,
            runbook=runbook,
            ticket=ticket,
        )
        return incident, IncidentResponse(
            status="accepted",
            incident_id=incident_id,
            severity=severity,
            normalized=True,
            next_action=next_action,
            runbook=runbook or {},
            ticket=ticket or {},
        )
