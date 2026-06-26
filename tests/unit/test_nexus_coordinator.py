from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.llm_router import LLMResponse
from nexus.audit.repository import MemoryAuditRepository
from nexus.connectors.itsm.jira import JiraConnector
from nexus.api.schemas.chat import ChatRequest
from nexus.api.schemas.incidents import IncidentIngestRequest
from nexus.api.schemas.monitoring import (
    AlertSilenceRequest,
    AlertWebhookRequest,
    MetricsIngestRequest,
    PrometheusQueryRequest,
)
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


@pytest.fixture
def coordinator():
    alertmanager = AsyncMock()
    alertmanager.fetch_alerts = AsyncMock(return_value=[
        {"status": {"state": "active"}, "labels": {"alertname": "HighCPU"}},
        {"status": {"state": "suppressed"}, "labels": {"alertname": "DiskWarn"}},
    ])
    alertmanager.create_silence = AsyncMock(return_value="sil-123")
    alertmanager.healthcheck = AsyncMock(return_value={
        "name": "Alertmanager",
        "kind": "alarm-routing",
        "status": "up",
        "endpoint": "http://alertmanager:9093",
    })

    prometheus = AsyncMock()
    prometheus.instant_query = AsyncMock(return_value=[
        {"metric": {"instance": "srv-01"}, "value": [1715550000, "98"]},
    ])
    prometheus.healthcheck = AsyncMock(return_value={
        "name": "Prometheus",
        "kind": "collector",
        "status": "up",
        "endpoint": "http://prometheus:9090",
    })
    grafana = AsyncMock()
    grafana.healthcheck = AsyncMock(return_value={
        "name": "Grafana",
        "kind": "visualization",
        "status": "up",
        "endpoint": "http://grafana:3000",
    })

    jira_cfg = type(
        "JiraCfg",
        (),
        {
            "jira_project_key": "NEXUS",
            "jira_configured": staticmethod(lambda: False),
        },
    )()

    llm_router = MagicMock()
    llm_router.call = AsyncMock(
        return_value=LLMResponse(
            content="Respuesta operativa de test",
            level_used=1,
            model_used="test-model",
            nivel_name="L1-Test",
            latency_ms=50,
        )
    )
    docker_diagnostics = AsyncMock()
    docker_diagnostics.run = AsyncMock(
        return_value={
            "status": "success",
            "technology": "docker",
            "container": "api-worker",
            "summary": "Contenedor api-worker detectado con estado restarting.",
            "observations": [
                "Estado Docker: status=restarting running=False restart_count=4",
                "Los logs recientes contienen errores o excepciones.",
            ],
            "evidence": {"docker_version": "28.0.0"},
        }
    )

    return NexusCoordinator(
        alertmanager=alertmanager,
        grafana=grafana,
        prometheus=prometheus,
        jira=JiraConnector(jira_cfg),
        incident_repository=MemoryIncidentRepository(),
        audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(),
        llm_router=llm_router,
        docker_diagnostics=docker_diagnostics,
    )


@pytest.mark.asyncio
async def test_handle_chat_devuelve_respuesta_operativa(coordinator):
    result = await coordinator.handle_chat(ChatRequest(message="hola", user_id="u1"))
    assert result.status in {"accepted", "degraded"}
    assert result.flow == "chat"
    assert result.agent
    assert result.audit_id.startswith("audit-")


@pytest.mark.asyncio
async def test_handle_chat_docker_recoge_evidencias_y_usa_llm(coordinator):
    result = await coordinator.handle_chat(
        ChatRequest(message="tengo una alarma de docker en el contenedor api-worker", user_id="u1")
    )

    coordinator._docker_diagnostics.run.assert_awaited_once()
    assert result.status in {"accepted", "degraded"}
    assert result.flow == "chat"
    assert result.agent


@pytest.mark.asyncio
async def test_handle_chat_linux_prepara_plan_por_tecnologia(coordinator):
    result = await coordinator.handle_chat(
        ChatRequest(message="tengo una alarma en el servidor linux web-prod-01", user_id="u1")
    )

    assert result.status in {"accepted", "degraded"}
    assert result.flow == "chat"
    assert result.agent


@pytest.mark.asyncio
async def test_handle_incident_normaliza_y_decide_siguiente_accion(coordinator):
    result = await coordinator.handle_incident(
        IncidentIngestRequest(
            source="alertmanager",
            title="CPU al 99%",
            severity="critical",
            payload={"host": "srv-01"},
        )
    )
    assert result.status == "accepted"
    assert result.severity == "critical"
    assert result.normalized is True
    assert result.next_action == "auto_diagnose"
    assert result.ticket["provider"] == "jira"
    assert result.runbook["recommended_execution"] == "manual_gate"


@pytest.mark.asyncio
async def test_get_alerts_resume_estado(coordinator):
    result = await coordinator.get_alerts()
    assert result.status == "success"
    assert result.total == 2
    assert result.firing == 1


@pytest.mark.asyncio
async def test_query_metrics_envuelve_resultado(coordinator):
    result = await coordinator.query_metrics(PrometheusQueryRequest(query="up"))
    assert result.status == "success"
    assert result.query == "up"
    assert result.result_count == 1


@pytest.mark.asyncio
async def test_ingest_metrics_acknowledge_counts(coordinator):
    result = await coordinator.ingest_metrics(
        MetricsIngestRequest(
            source="desktop-agent",
            metrics={"cpu": 91, "ram": 77},
            alerts=[{"name": "HighCPU"}],
        )
    )
    assert result.status == "accepted"
    assert result.source == "desktop-agent"
    assert result.metrics_count == 2
    assert result.alerts_count == 1


@pytest.mark.asyncio
async def test_silence_alert_devuelve_id(coordinator):
    result = await coordinator.silence_alert(
        AlertSilenceRequest(alert_name="HighCPU", created_by="tester")
    )
    assert result.status == "success"
    assert result.silence_id == "sil-123"


@pytest.mark.asyncio
async def test_list_incidents_devuelve_persistidos(coordinator):
    await coordinator.handle_incident(
        IncidentIngestRequest(source="api", title="Disk full", severity="warning", payload={"alert_name": "DiskFull"})
    )
    result = await coordinator.list_incidents()
    assert result.status == "success"
    assert result.total == 1
    assert result.incidents[0]["title"] == "Disk full"


@pytest.mark.asyncio
async def test_list_audit_entries_recoge_acciones(coordinator):
    await coordinator.handle_chat(ChatRequest(message="hola", user_id="u1"))
    result = await coordinator.list_audit_entries()
    assert result["status"] == "success"
    assert result["total"] >= 1


@pytest.mark.asyncio
async def test_list_runbooks_expone_catalogo(coordinator):
    result = await coordinator.list_runbooks()
    assert result.status == "success"
    assert result.total >= 1


@pytest.mark.asyncio
async def test_get_y_actualizar_incidente(coordinator):
    created = await coordinator.handle_incident(
        IncidentIngestRequest(
            source="api",
            title="Disk full",
            severity="warning",
            payload={"alert_name": "DiskFull"},
        )
    )
    fetched = await coordinator.get_incident(created.incident_id)
    assert fetched["status"] == "success"
    assert fetched["incident"]["title"] == "Disk full"

    updated = await coordinator.update_incident(
        created.incident_id,
        status="acknowledged",
        actor="operator-1",
        owner="operator-1",
    )
    assert updated["status"] == "success"
    assert updated["incident"]["status"] == "acknowledged"
    assert updated["incident"]["owner"] == "operator-1"


@pytest.mark.asyncio
async def test_execute_incident_action_preview(coordinator):
    created = await coordinator.handle_incident(
        IncidentIngestRequest(
            source="api",
            title="Disk full",
            severity="warning",
            payload={"alert_name": "DiskFull"},
        )
    )
    result = await coordinator.execute_incident_action(
        created.incident_id,
        action_name="ticket",
        actor="operator-1",
        dry_run=True,
    )
    assert result["status"] == "preview"
    assert result["action_name"] == "ticket"


@pytest.mark.asyncio
async def test_execute_incident_action_bloquea_fuera_de_runbook(coordinator):
    created = await coordinator.handle_incident(
        IncidentIngestRequest(
            source="api",
            title="CPU al 99%",
            severity="critical",
            payload={"alert_name": "HighCPU"},
        )
    )
    result = await coordinator.execute_incident_action(
        created.incident_id,
        action_name="restart_service",
        actor="operator-1",
        dry_run=True,
    )
    assert result["status"] == "blocked"


@pytest.mark.asyncio
async def test_handle_alertmanager_webhook_crea_y_resuelve_incidentes(coordinator):
    firing = await coordinator.handle_alertmanager_webhook(
        AlertWebhookRequest(
            receiver="nexus-admins",
            alerts=[
                {
                    "status": "firing",
                    "fingerprint": "fp-001",
                    "labels": {"alertname": "DiskFull", "severity": "critical"},
                    "annotations": {"summary": "Disk full on srv-01"},
                    "startsAt": "2026-05-13T18:00:00Z",
                }
            ],
        )
    )
    assert firing.incidents_created == 1

    resolved = await coordinator.handle_alertmanager_webhook(
        AlertWebhookRequest(
            receiver="nexus-admins",
            alerts=[
                {
                    "status": "resolved",
                    "fingerprint": "fp-001",
                    "labels": {"alertname": "DiskFull", "severity": "critical"},
                }
            ],
        )
    )
    assert resolved.incidents_resolved == 1
    incident = await coordinator.get_incident("fp-001")
    assert incident["incident"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_get_collector_status_devuelve_fuentes_integradas(coordinator):
    result = await coordinator.get_collector_status()
    assert result["status"] == "success"
    assert result["overall"] == "up"
    assert len(result["collectors"]) == 3
