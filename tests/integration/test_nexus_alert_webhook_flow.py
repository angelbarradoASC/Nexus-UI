from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.audit.repository import MemoryAuditRepository
from nexus.connectors.itsm.jira import JiraConnector
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator
from nexus.bootstrap import register_nexus_v1


class _Runtime:
    def __init__(self, coordinator):
        self.coordinator = coordinator


def _build_client():
    alertmanager = AsyncMock()
    alertmanager.fetch_alerts = AsyncMock(return_value=[])
    alertmanager.create_silence = AsyncMock(return_value="sil-test")

    prometheus = AsyncMock()
    prometheus.instant_query = AsyncMock(return_value=[])

    jira_cfg = type(
        "JiraCfg",
        (),
        {
            "jira_project_key": "NEXUS",
            "jira_configured": staticmethod(lambda: False),
        },
    )()
    llm_router = MagicMock()
    llm_router.call = AsyncMock()

    app = FastAPI()
    register_nexus_v1(app)
    app.state.nexus_runtime = _Runtime(
        coordinator=NexusCoordinator(
            alertmanager=alertmanager,
            grafana=AsyncMock(),
            prometheus=prometheus,
            jira=JiraConnector(jira_cfg),
            incident_repository=MemoryIncidentRepository(),
            audit_repository=MemoryAuditRepository(),
            runbooks=RunbookRegistry(),
            llm_router=llm_router,
        )
    )
    return TestClient(app, raise_server_exceptions=True)


def test_alertmanager_webhook_crea_incidente_y_lo_resuelve():
    firing_payload = {
        "receiver": "nexus-admins",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "fp-live-001",
                "labels": {
                    "alertname": "DiskFull",
                    "severity": "critical",
                    "instance": "srv-app-01",
                },
                "annotations": {
                    "summary": "Disk full on srv-app-01",
                    "description": "Filesystem over threshold",
                },
            }
        ],
    }
    resolved_payload = {
        "receiver": "nexus-admins",
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "fingerprint": "fp-live-001",
                "labels": {
                    "alertname": "DiskFull",
                    "severity": "critical",
                    "instance": "srv-app-01",
                },
            }
        ],
    }

    with _build_client() as client:
        created = client.post("/api/nexus/monitoring/webhook", json=firing_payload)
        incident = client.get("/api/nexus/incidents/fp-live-001")
        resolved = client.post("/api/nexus/monitoring/webhook", json=resolved_payload)
        incident_after = client.get("/api/nexus/incidents/fp-live-001")
        audit = client.get("/api/nexus/audit")

    assert created.status_code == 200
    assert created.json()["incidents_created"] == 1
    assert incident.status_code == 200
    assert incident.json()["incident"]["status"] == "open"
    assert incident.json()["incident"]["runbook"]["summary"]
    assert resolved.status_code == 200
    assert resolved.json()["incidents_resolved"] == 1
    assert incident_after.status_code == 200
    assert incident_after.json()["incident"]["status"] == "resolved"
    assert audit.status_code == 200
    assert audit.json()["total"] >= 2
