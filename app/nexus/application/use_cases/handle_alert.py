"""Primary use case for processing a monitoring alert."""

from __future__ import annotations

from nexus.api.schemas.incidents import IncidentIngestRequest, IncidentResponse
from nexus.monitoring.alert_pipeline import AlertPipeline


class HandleAlertUseCase:
    """Use case wrapper for turning an alert into an incident flow."""

    def __init__(self, pipeline: AlertPipeline) -> None:
        self._pipeline = pipeline

    async def execute(self, payload: IncidentIngestRequest) -> IncidentResponse:
        return await self._pipeline.open_incident(payload)
