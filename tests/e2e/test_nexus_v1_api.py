from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.bootstrap import register_nexus_v1
from nexus.application.services.agent_runtime_service import AgentRuntimeService


@dataclass
class _FakeRuntime:
    coordinator: object
    agent_runtime: object
    outreach: object
    crm: object
    prospecting: object


class _FakeOutreach:
    async def status(self):
        return {
            "status": "success",
            "enabled": False,
            "account": {
                "email": "vicentearaizeta@sls.assetsconsultores.es",
                "sender_name": "Vicente Araizeta",
                "smtp": {"configured": False, "status": "not_configured"},
                "imap": {"configured": False, "status": "not_configured"},
            },
            "daily_cap_default": 20,
            "sent_today": 0,
            "campaigns_total": 1,
            "recent_campaigns": [{"campaign_id": "out-001", "campaign_name": "Demo"}],
            "recent_events": [],
        }

    async def list_events(self, limit=50):
        return {
            "status": "success",
            "total": 1,
            "events": [{
                "event_id": "evt-001",
                "event_type": "email_preview",
                "recipient_email": "alice@example.com",
                "company": "Example",
                "subject": "Idea para Example",
                "delivery_status": "preview_only",
                "step_index": 0,
                "dry_run": True,
            }],
        }

    async def list_campaigns(self, limit=20):
        return {
            "status": "success",
            "total": 1,
            "campaigns": [{"campaign_id": "out-001", "campaign_name": "Demo"}],
        }

    async def launch_campaign(self, payload):
        return {
            "status": "accepted",
            "campaign_id": "out-001",
            "dry_run": payload.get("dry_run", True),
            "executed_count": 1,
            "total_prospects": 1,
            "events": [{
                "event_id": "evt-001",
                "event_type": "email_preview",
                "recipient_email": "alice@example.com",
                "company": "Example",
                "subject": "Idea para Example",
                "delivery_status": "preview_only",
                "step_index": 0,
                "dry_run": True,
            }],
        }

    async def run_campaign(self, campaign_id, dry_run=True):
        return {
            "status": "accepted",
            "campaign_id": campaign_id,
            "dry_run": dry_run,
            "executed_count": 1,
            "events": [],
        }


class _FakeCRM:
    async def status(self):
        return {
            "status": "success",
            "provider": "assets-web-api",
            "discovered_source": r"C:\DEV\GitHub\assets-web-api",
            "connector": {
                "provider": "assets-web-api",
                "configured": False,
                "status": "not_configured",
                "base_url": "http://127.0.0.1:8000",
                "username": "",
            },
            "campaigns_total": 1,
            "pending_prospects": 3,
            "recent_campaigns": [{"campaign_id": "out-001", "campaign_name": "Demo"}],
        }

    async def sync_campaign(self, campaign_id, *, dry_run=True, limit=3):
        return {
            "status": "accepted",
            "campaign_id": campaign_id,
            "dry_run": dry_run,
            "synced_count": limit,
            "results": [{
                "status": "preview",
                "provider": "assets-web-api",
                "prospect_id": "pros-001",
                "email": "alice@example.com",
            }],
        }


class _FakeCoordinator:
    def __init__(self):
        self._incident = {
            "incident_id": "inc-test",
            "title": "Database down",
            "severity": "critical",
            "status": "open",
            "next_action": "triage",
            "source": "api",
            "runbook": {"summary": "demo", "auto_actions": ["ticket"]},
        }

    async def health_snapshot(self):
        return {
            "status": "ok",
            "surface": "nexus-v1",
            "flows": ["chat", "incidents", "monitoring"],
            "workers": [{"name": "monitoring-worker", "status": "ready"}],
        }

    async def get_collector_status(self):
        return {
            "status": "success",
            "overall": "up",
            "collectors": [
                {"name": "Prometheus", "kind": "collector", "status": "up"},
                {"name": "Alertmanager", "kind": "alarm-routing", "status": "down"},
                {"name": "Grafana", "kind": "visualization", "status": "up"},
            ],
        }

    async def handle_chat(self, payload):
        return {
            "status": "accepted",
            "response": f"echo:{payload.message}",
            "agent": "fake",
            "flow": "chat",
            "audit_id": "audit-test",
        }

    async def handle_incident(self, payload):
        return {
            "status": "accepted",
            "incident_id": "inc-test",
            "severity": payload.severity,
            "normalized": True,
            "next_action": "triage",
            "runbook": {"summary": "demo"},
            "ticket": {"provider": "jira", "status": "simulated"},
        }

    async def get_alerts(self):
        return {
            "status": "success",
            "total": 1,
            "firing": 1,
            "alerts": [{"labels": {"alertname": "HighCPU"}}],
        }

    async def query_metrics(self, payload):
        return {
            "status": "success",
            "query": payload.query,
            "result_count": 1,
            "result": [{"metric": {"job": "node"}, "value": [1, "1"]}],
        }

    async def ingest_metrics(self, payload):
        return {
            "status": "accepted",
            "source": payload.source,
            "metrics_count": len(payload.metrics),
            "alerts_count": len(payload.alerts),
        }

    async def silence_alert(self, payload):
        return {
            "status": "success",
            "silence_id": f"silence-{payload.alert_name}",
        }

    async def list_incidents(self):
        return {
            "status": "success",
            "total": 1,
            "incidents": [self._incident],
        }

    async def get_incident(self, incident_id):
        return {"status": "success", "incident": self._incident}

    async def update_incident(self, incident_id, *, status, actor, owner=None, resolution_note=None):
        self._incident["status"] = status
        self._incident["owner"] = owner
        self._incident["resolution_note"] = resolution_note
        return {"status": "success", "incident": self._incident}

    async def execute_incident_action(self, incident_id, *, action_name, actor, dry_run):
        return {
            "status": "preview" if dry_run else "executed",
            "incident_id": incident_id,
            "action_name": action_name,
            "result": "dry_run_only" if dry_run else {"status": "accepted"},
        }

    async def handle_alertmanager_webhook(self, payload):
        return {
            "status": "accepted",
            "received": len(payload.alerts),
            "incidents_created": 1,
            "incidents_resolved": 0,
        }

    async def list_audit_entries(self):
        return {
            "status": "success",
            "total": 1,
            "entries": [{
                "audit_id": "audit-test",
                "flow": "chat",
                "action": "handle_chat",
                "actor": "demo-user",
                "status": "accepted",
                "timestamp": "2026-05-13T10:00:00+00:00",
            }],
        }

    async def list_runbooks(self):
        return {
            "status": "success",
            "total": 1,
            "runbooks": [{
                "alert_name": "HighCPU",
                "summary": "demo runbook",
                "auto_actions": ["diagnose_only"],
            }],
        }


class _FakeProspecting:
    async def run(self, payload):
        # La ruta real (/api/nexus/prospecting/run) siempre pasa el objeto
        # ProspectingRunRequest tal cual (FastAPI ya lo parsea del body) —
        # nunca un dict, asi que es .dry_run (atributo), no .get("dry_run").
        return {
            "status": "completed",
            "run_id": "pros-001",
            "summary": {"usable_results": 1, "discarded": 0, "duplicates": 0},
            "results_count": 1,
            "discarded_count": 0,
            "dry_run": payload.dry_run,
            "queries": ["restaurante zaragoza eventos"],
        }

    async def get_run(self, run_id):
        return {
            "status": "completed",
            "run_id": run_id,
            "started_at": "2026-06-04T09:00:00+00:00",
            "finished_at": "2026-06-04T09:01:00+00:00",
            "brief": {"vertical": "restaurants", "city": "Zaragoza", "desired_count": 20},
            "queries": ["restaurante zaragoza eventos"],
            "summary": {"usable_results": 1, "discarded": 0, "duplicates": 0},
            "results": [{
                "result_id": "prosr-001",
                "name": "Restaurante Fuego",
                "vertical": "restaurants",
                "city": "Zaragoza",
                "website": "https://fuego.example.com",
                "email": "reservas@fuego.example.com",
                "role": "Nuevas Tecnologías",
                "phone": "976123123",
                "score": 85,
                "priority": "Alta",
                "crm_state": "pending",
                "source_url": "https://fuego.example.com/contacto",
                "reason": "restaurante con señales de calidad",
            }],
            "discarded": [],
        }

    async def list_results(self, **kwargs):
        return {
            "status": "success",
            "results": [{
                "result_id": "prosr-001",
                "name": "Restaurante Fuego",
                "score": 85,
            }],
        }

    async def list_discarded(self, **kwargs):
        return {
            "status": "success",
            "discarded": [],
        }

    async def push_result_to_crm(self, result_id, *, dry_run=True):
        return {
            "status": "accepted",
            "dry_run": dry_run,
            "result_id": result_id,
            "company_payload": {"name": "Restaurante Fuego"},
            "pipeline_payload": {"pipeline_stage": "new"},
            "note_payload": {"note_type": "note"},
        }

    async def push_valid_to_crm(self, run_id, *, dry_run=True):
        return {
            "status": "accepted",
            "run_id": run_id,
            "dry_run": dry_run,
            "pushed_count": 1,
            "results": [{"status": "accepted", "result_id": "prosr-001"}],
        }

    async def resume_run(self, run_id):
        return {
            "status": "completed",
            "run_id": run_id,
            "summary": {"usable_results": 1, "discarded": 0, "duplicates": 0},
            "results_count": 1,
            "discarded_count": 0,
            "dry_run": True,
            "queries": ["restaurante zaragoza eventos"],
        }


def _build_client():
    app = FastAPI()
    register_nexus_v1(app)
    app.state.nexus_runtime = _FakeRuntime(
        coordinator=_FakeCoordinator(),
        agent_runtime=AgentRuntimeService(),
        outreach=_FakeOutreach(),
        crm=_FakeCRM(),
        prospecting=_FakeProspecting(),
    )
    return TestClient(app, raise_server_exceptions=True)


def test_nexus_v1_health():
    with _build_client() as client:
        response = client.get("/api/nexus/health")
    assert response.status_code == 200
    assert response.json()["surface"] == "nexus-v1"
    assert response.json()["workers"][0]["name"] == "monitoring-worker"


def test_nexus_agent_catalog():
    with _build_client() as client:
        response = client.get("/api/nexus/agents/catalog?surface=desktop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery_model"] == "server_resident"
    assert payload["contracts"]["run_model"].endswith("AgentRun")
    assert {agent["agent_id"] for agent in payload["agents"]} >= {
        "supervisor",
        "operator",
        "shell",
        "sales",
    }


def test_nexus_agent_runs_bootstrap_shared_contract():
    with _build_client() as client:
        created = client.post(
            "/api/nexus/agents/runs",
            json={
                "message": "revisa el estado de alertas",
                "user_id": "u1",
                "source_surface": "desktop",
                "mode": "operator",
            },
        )
        run_id = created.json()["run_id"]
        detail = client.get(f"/api/nexus/agents/runs/{run_id}")
        listed = client.get("/api/nexus/agents/runs?surface=desktop&agent_id=operator")

    assert created.status_code == 200
    assert created.json()["agent_id"] == "operator"
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert listed.json()["runs"][0]["agent_id"] == "operator"


def test_nexus_v1_page():
    with _build_client() as client:
        response = client.get("/nexus-v1")
    assert response.status_code == 200
    assert "Operador" in response.text
    assert "Auto refresh" in response.text
    assert "Thunderbird" not in response.text
    assert "Email outreach" not in response.text
    assert "CRM interno" not in response.text
    assert "Sales" in response.text


def test_nexus_sales_page():
    with _build_client() as client:
        response = client.get("/nexus-sales")
    assert response.status_code == 200
    assert "Sales" in response.text
    assert "Email outreach" in response.text
    assert "CRM interno" in response.text
    assert "ProspectingAgent" in response.text


def test_open_nexus_models_page():
    with _build_client() as client:
        response = client.get("/open-nexus/models")
    assert response.status_code == 200
    assert "Modelos" in response.text
    assert "Guardar y aplicar" in response.text


def test_nexus_v1_chat():
    with _build_client() as client:
        response = client.post("/api/nexus/chat", json={"message": "hola nexus", "user_id": "u1"})
    assert response.status_code == 200
    assert response.json()["response"] == "echo:hola nexus"


def test_nexus_v1_incident_intake():
    with _build_client() as client:
        response = client.post(
            "/api/nexus/incidents",
            json={"source": "api", "title": "Database down", "severity": "critical", "payload": {}},
        )
    assert response.status_code == 200
    assert response.json()["incident_id"] == "inc-test"


def test_nexus_v1_incident_lifecycle():
    with _build_client() as client:
        detail = client.get("/api/nexus/incidents/inc-test")
        update = client.patch(
            "/api/nexus/incidents/inc-test",
            json={"status": "acknowledged", "actor": "tester", "owner": "tester"},
        )
        action = client.post(
            "/api/nexus/incidents/inc-test/actions",
            json={"action_name": "ticket", "actor": "tester", "dry_run": True},
        )

    assert detail.status_code == 200
    assert detail.json()["incident"]["incident_id"] == "inc-test"
    assert update.status_code == 200
    assert update.json()["incident"]["status"] == "acknowledged"
    assert action.status_code == 200
    assert action.json()["status"] == "preview"


def test_nexus_v1_monitoring_endpoints():
    with _build_client() as client:
        collectors = client.get("/api/nexus/monitoring/collectors")
        alerts = client.get("/api/nexus/monitoring/alerts")
        query = client.post("/api/nexus/monitoring/query", json={"query": "up"})
        ingest = client.post(
            "/api/nexus/monitoring/ingest",
            json={"source": "desktop", "metrics": {"cpu": 80}, "alerts": [{"name": "HighCPU"}]},
        )
        silence = client.post(
            "/api/nexus/monitoring/silence",
            json={"alert_name": "HighCPU", "created_by": "tester", "duration_seconds": 600},
        )
        runbooks = client.get("/api/nexus/monitoring/runbooks")
        webhook = client.post(
            "/api/nexus/monitoring/webhook",
            json={
                "receiver": "nexus-admins",
                "alerts": [{
                    "status": "firing",
                    "fingerprint": "fp-001",
                    "labels": {"alertname": "DiskFull", "severity": "critical"},
                    "annotations": {"summary": "Disk full on srv-01"},
                }],
            },
        )
        incidents = client.get("/api/nexus/incidents")
        audit = client.get("/api/nexus/audit")

    assert collectors.status_code == 200
    assert collectors.json()["collectors"][0]["name"] == "Prometheus"
    assert alerts.status_code == 200
    assert alerts.json()["total"] == 1
    assert query.status_code == 200
    assert query.json()["query"] == "up"
    assert ingest.status_code == 200
    assert ingest.json()["metrics_count"] == 1
    assert silence.status_code == 200
    assert silence.json()["silence_id"] == "silence-HighCPU"
    assert runbooks.status_code == 200
    assert runbooks.json()["total"] == 1
    assert webhook.status_code == 200
    assert webhook.json()["received"] == 1
    assert incidents.status_code == 200
    assert incidents.json()["total"] == 1
    assert audit.status_code == 200


def test_nexus_v1_outreach_endpoints():
    with _build_client() as client:
        status = client.get("/api/nexus/outreach/status")
        events = client.get("/api/nexus/outreach/events")
        campaigns = client.get("/api/nexus/outreach/campaigns")
        launch = client.post(
            "/api/nexus/outreach/launch",
            json={
                "campaign_name": "Demo campaign",
                "proposition": "Servicios gestionados y ciberseguridad para pymes",
                "csv_text": "email,first_name,company\nalice@example.com,Alice,Example",
                "dry_run": True,
            },
        )

    assert status.status_code == 200
    assert status.json()["account"]["email"] == "vicentearaizeta@sls.assetsconsultores.es"
    assert events.status_code == 200
    assert events.json()["total"] == 1
    assert campaigns.status_code == 200
    assert campaigns.json()["total"] == 1
    assert launch.status_code == 200
    assert launch.json()["campaign_id"] == "out-001"


def test_nexus_v1_mail_endpoints_removed():
    with _build_client() as client:
        status = client.get("/api/nexus/mail/status")
        priority = client.get("/api/nexus/mail/priority")

    assert status.status_code == 404
    assert priority.status_code == 404


def test_nexus_v1_crm_endpoints():
    with _build_client() as client:
        status = client.get("/api/nexus/crm/status")
        sync = client.post("/api/nexus/crm/campaigns/out-001/sync", json={"dry_run": True, "limit": 3})

    assert status.status_code == 200
    assert status.json()["provider"] == "assets-web-api"
    assert sync.status_code == 200
    assert sync.json()["synced_count"] == 3


def test_nexus_v1_prospecting_endpoints():
    with _build_client() as client:
        run = client.post(
            "/api/nexus/prospecting/run",
            json={"vertical": "restaurants", "city": "Zaragoza", "desired_count": 20, "dry_run": True},
        )
        detail = client.get("/api/nexus/prospecting/runs/pros-001")
        results = client.get("/api/nexus/prospecting/results")
        push_one = client.post(
            "/api/nexus/prospecting/results/prosr-001/push-to-crm",
            json={"dry_run": True},
        )
        push_valid = client.post(
            "/api/nexus/prospecting/push-valid-to-crm",
            json={"run_id": "pros-001", "dry_run": True},
        )
        resume = client.post("/api/nexus/prospecting/runs/pros-001/resume")

    assert run.status_code == 200
    assert run.json()["run_id"] == "pros-001"
    assert detail.status_code == 200
    assert detail.json()["results"][0]["name"] == "Restaurante Fuego"
    assert results.status_code == 200
    assert results.json()["results"][0]["score"] == 85
    assert push_one.status_code == 200
    assert push_one.json()["result_id"] == "prosr-001"
    assert push_valid.status_code == 200
    assert push_valid.json()["pushed_count"] == 1
    assert resume.status_code == 200
