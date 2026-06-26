"""Monitoring request and response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PrometheusQueryRequest(BaseModel):
    """Request payload for a Prometheus query."""

    query: str = Field(min_length=1)


class PrometheusQueryResponse(BaseModel):
    """Response payload for a Prometheus query."""

    status: str
    query: str
    result_count: int
    result: list[dict[str, Any]]


class MetricsIngestRequest(BaseModel):
    """Payload for ingesting local metrics and alert summaries."""

    source: str = Field(default="edge")
    metrics: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)


class MetricsIngestResponse(BaseModel):
    """Acknowledgement of metrics ingestion."""

    status: str
    source: str
    metrics_count: int
    alerts_count: int


class AlertsResponse(BaseModel):
    """Current alert set exposed through Nexus."""

    status: str
    total: int
    firing: int
    alerts: list[dict[str, Any]]


class AlertSilenceRequest(BaseModel):
    """Create a silence in Alertmanager."""

    alert_name: str = Field(min_length=1)
    created_by: str = Field(default="nexus")
    duration_seconds: int = Field(default=3600, ge=60, le=86400)
    comment: str = Field(default="Silenced via Nexus")


class AlertSilenceResponse(BaseModel):
    """Acknowledgement of a silence request."""

    status: str
    silence_id: str


class RunbooksResponse(BaseModel):
    """Available runbooks exposed by Nexus."""

    status: str
    total: int
    runbooks: list[dict[str, Any]]


class AlertWebhookRequest(BaseModel):
    """Alertmanager webhook payload forwarded into Nexus."""

    version: str = Field(default="4")
    groupKey: str | None = None
    status: str = Field(default="firing")
    receiver: str | None = None
    groupLabels: dict[str, Any] = Field(default_factory=dict)
    commonLabels: dict[str, Any] = Field(default_factory=dict)
    commonAnnotations: dict[str, Any] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[dict[str, Any]] = Field(default_factory=list)


class AlertWebhookResponse(BaseModel):
    """Acknowledgement for a webhook batch received from Alertmanager."""

    status: str
    received: int
    incidents_created: int
    incidents_resolved: int
