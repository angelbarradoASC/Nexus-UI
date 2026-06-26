"""Monitoring alert intake and routing pipeline."""

from __future__ import annotations

from nexus.api.schemas.incidents import IncidentIngestRequest, IncidentResponse
from nexus.incidents.incident_pipeline import IncidentPipeline


class AlertPipeline:
    """Bridge monitoring alerts into the incident lifecycle."""

    def __init__(self, incident_pipeline: IncidentPipeline) -> None:
        self._incident_pipeline = incident_pipeline

    async def open_incident(
        self,
        payload: IncidentIngestRequest,
        *,
        runbook: dict | None = None,
        ticket: dict | None = None,
    ) -> tuple[object, IncidentResponse]:
        return await self._incident_pipeline.process(payload, runbook=runbook, ticket=ticket)
