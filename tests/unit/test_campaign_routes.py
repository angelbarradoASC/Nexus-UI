"""tests/unit/test_campaign_routes.py

Rutas HTTP de la Campaña (app/nexus/api/routes/campaign.py) — cubre dos
huecos reales encontrados en la revision de la UI (2026-09-30):

1. PUT /campaign/config mezclaba TODAS las lineas en un solo dict plano —
   no habia forma de actualizar solo la linea "ia_adopcion" sin pisar
   "default". Ahora acepta "line" y enruta al dict correcto.
2. GET /campaign/results usaba report['new_campaign'] (una sola linea) —
   escondia en silencio los resultados de cualquier otra linea activa el
   mismo dia. Ahora junta los resultados de todas las lineas del report.
3. PUT /campaign/global-toggle — interruptor GLOBAL separado, para que
   pausar una linea nunca se confunda con pausar TODO (follow-ups
   incluidos).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.api.dependencies.auth import get_campaign_agent, get_prospecting_manager
from nexus.api.routes import campaign as campaign_routes


class _FakeCampaignAgent:
    def __init__(self, cfg: dict):
        self._cfg = cfg

    def load_config(self) -> dict:
        return self._cfg

    def save_config(self, cfg: dict) -> None:
        self._cfg = cfg


class _FakeProspecting:
    def __init__(self, results_by_run: dict[str, list[dict]]):
        self._results_by_run = results_by_run

    async def list_results(self, *, run_id: str | None = None, **_kwargs) -> dict:
        return {"status": "success", "results": self._results_by_run.get(run_id, [])}


class _FakeScheduler:
    def __init__(self, last_run_report: dict | None):
        self._last_run_report = last_run_report

    def describe(self) -> dict:
        return {"last_run_report": self._last_run_report}


def _client(*, cfg: dict, results_by_run: dict | None = None, last_run_report: dict | None = None) -> tuple[TestClient, _FakeCampaignAgent]:
    app = FastAPI()
    app.include_router(campaign_routes.router)
    agent = _FakeCampaignAgent(cfg)
    app.dependency_overrides[get_campaign_agent] = lambda: agent
    app.dependency_overrides[get_prospecting_manager] = lambda: _FakeProspecting(results_by_run or {})
    app.state.nexus_scheduler = _FakeScheduler(last_run_report)
    return TestClient(app), agent


def _base_cfg() -> dict:
    return {
        "enabled": True,
        "default_enabled": False,
        "vertical": "custom",
        "sender_name": "Vicente",
        "additional_campaigns": [
            {"name": "ia_adopcion", "enabled": True, "vertical": "ia_adopcion", "proposition": "adopcion de IA"},
        ],
    }


def test_put_config_default_line_does_not_touch_additional_campaigns():
    client, agent = _client(cfg=_base_cfg())

    resp = client.put("/campaign/config", json={"line": "default", "proposition": "nueva propuesta pyme"})

    assert resp.status_code == 200
    assert agent.load_config()["proposition"] == "nueva propuesta pyme"
    assert agent.load_config()["additional_campaigns"][0]["proposition"] == "adopcion de IA"


def test_put_config_updates_only_the_named_additional_line():
    client, agent = _client(cfg=_base_cfg())

    resp = client.put("/campaign/config", json={"line": "ia_adopcion", "proposition": "propuesta IA actualizada", "opportunity_threshold": 60})

    assert resp.status_code == 200
    extra = agent.load_config()["additional_campaigns"][0]
    assert extra["proposition"] == "propuesta IA actualizada"
    assert extra["opportunity_threshold"] == 60
    assert agent.load_config()["vertical"] == "custom"  # default intacto


def test_put_config_unknown_line_returns_404():
    client, _ = _client(cfg=_base_cfg())

    resp = client.put("/campaign/config", json={"line": "no_existe", "proposition": "x"})

    assert resp.status_code == 404


def test_global_toggle_sets_top_level_enabled_only():
    client, agent = _client(cfg=_base_cfg())

    resp = client.put("/campaign/global-toggle", json={"enabled": False})

    assert resp.status_code == 200
    cfg = agent.load_config()
    assert cfg["enabled"] is False
    assert cfg["default_enabled"] is False  # no lo toca, sigue como estaba
    assert cfg["additional_campaigns"][0]["enabled"] is True  # tampoco


def test_results_merges_every_line_from_last_run_report():
    report = {
        "campaigns": {
            "default": {"run_id": "run-default", "status": "pending_review"},
            "ia_adopcion": {"run_id": "run-ia", "status": "pending_review"},
        }
    }
    results_by_run = {
        "run-default": [{"result_id": "r1", "vertical": "custom"}],
        "run-ia": [{"result_id": "r2", "vertical": "ia_adopcion"}, {"result_id": "r3", "vertical": "ia_adopcion"}],
    }
    client, _ = _client(cfg=_base_cfg(), results_by_run=results_by_run, last_run_report=report)

    resp = client.get("/campaign/results")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body["run_ids"]) == {"run-default", "run-ia"}
    assert {r["result_id"] for r in body["results"]} == {"r1", "r2", "r3"}


def test_results_empty_when_no_report_yet():
    client, _ = _client(cfg=_base_cfg(), last_run_report=None)

    resp = client.get("/campaign/results")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "run_ids": [], "results": []}
