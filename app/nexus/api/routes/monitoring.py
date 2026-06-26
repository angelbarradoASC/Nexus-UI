"""Monitoring and alert routes for Nexus v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nexus.api.dependencies.auth import get_coordinator
from nexus.api.schemas.monitoring import (
    AlertSilenceRequest,
    AlertSilenceResponse,
    AlertWebhookRequest,
    AlertWebhookResponse,
    AlertsResponse,
    MetricsIngestRequest,
    MetricsIngestResponse,
    PrometheusQueryRequest,
    PrometheusQueryResponse,
    RunbooksResponse,
)
from nexus.orchestration.coordinator import NexusCoordinator

router = APIRouter()


@router.get("/monitoring/alerts", response_model=AlertsResponse)
async def get_alerts(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> AlertsResponse:
    """Read current alerts from the monitoring surface."""
    return await coordinator.get_alerts()


@router.post("/monitoring/query", response_model=PrometheusQueryResponse)
async def query_metrics(
    payload: PrometheusQueryRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> PrometheusQueryResponse:
    """Query Prometheus for operational context."""
    return await coordinator.query_metrics(payload)


@router.post("/monitoring/ingest", response_model=MetricsIngestResponse)
async def ingest_metrics(
    payload: MetricsIngestRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> MetricsIngestResponse:
    """Ingest metrics and alerts from local or edge agents."""
    return await coordinator.ingest_metrics(payload)


@router.post("/monitoring/silence", response_model=AlertSilenceResponse)
async def silence_alert(
    payload: AlertSilenceRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> AlertSilenceResponse:
    """Create an Alertmanager silence through Nexus."""
    return await coordinator.silence_alert(payload)


@router.get("/monitoring/runbooks", response_model=RunbooksResponse)
async def get_runbooks(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> RunbooksResponse:
    """Expose runbooks used by the monitoring surface."""
    return await coordinator.list_runbooks()


@router.get("/monitoring/collectors")
async def get_collectors_status(
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> dict[str, object]:
    """Expose the operational state of integrated collection and alarm sources."""
    return await coordinator.get_collector_status()


@router.post("/monitoring/webhook", response_model=AlertWebhookResponse)
async def receive_alertmanager_webhook(
    payload: AlertWebhookRequest,
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> AlertWebhookResponse:
    """Receive Alertmanager webhook batches and convert them into Nexus actions."""
    return await coordinator.handle_alertmanager_webhook(payload)
