"""tests/unit/test_campaign_agent_review_queue.py

Tests unitarios para la cola de revision humana de CampaignAgent —
require_manual_approval=true (default) deja los QUALIFIED pendientes de
decision en vez de auto-enviar, y alimenta el CRM con todo lo descubierto.
"""

from __future__ import annotations

import pytest

from nexus.prospecting.campaign_agent import CampaignAgent


class _FakeProspectingService:
    def __init__(self, *, results: list[dict] | None = None):
        self.results = results or []
        self.run_calls: list[dict] = []
        self.push_valid_calls: list[tuple] = []
        self.mark_lead_stage_calls: list[tuple] = []

    async def run(self, request) -> dict:
        self.run_calls.append(request)
        return {"run_id": "run-test-1"}

    async def list_results(self, *, run_id=None, crm_state=None, lead_stage=None) -> dict:
        results = self.results
        if crm_state:
            results = [r for r in results if r.get("crm_state") == crm_state]
        if lead_stage:
            results = [r for r in results if r.get("lead_stage") == lead_stage]
        return {"status": "success", "results": results}

    async def push_valid_to_crm(self, run_id: str, *, dry_run: bool = True) -> dict:
        self.push_valid_calls.append((run_id, dry_run))
        return {"status": "accepted", "run_id": run_id, "pushed_count": len(self.results)}

    async def mark_lead_stage(self, result_id: str, lead_stage: str) -> dict:
        self.mark_lead_stage_calls.append((result_id, lead_stage))
        for r in self.results:
            if r.get("result_id") == result_id:
                r["lead_stage"] = lead_stage
        return {"status": "ok", "result_id": result_id, "lead_stage": lead_stage}


class _FakeOutreachManager:
    def __init__(self):
        self.launch_calls: list[dict] = []

    async def launch_campaign(self, payload: dict) -> dict:
        self.launch_calls.append(payload)
        return {"campaign_id": "camp-test-1", "executed_count": len(payload.get("prospects", []))}


class _FakeCRMService:
    def __init__(self):
        self.sync_calls: list[tuple] = []

    async def sync_campaign(self, campaign_id: str, *, limit: int, dry_run: bool) -> dict:
        self.sync_calls.append((campaign_id, limit, dry_run))
        return {"status": "ok"}


def _qualified_result(result_id: str, name: str) -> dict:
    return {
        "result_id": result_id,
        "name": name,
        "email": f"{result_id}@example.com",
        "lead_stage": "QUALIFIED",
        "crm_state": "pending",
        "opportunity_score": 70,
    }


def _agent(tmp_path, *, results=None, require_manual_approval: bool = True):
    prospecting = _FakeProspectingService(results=results)
    outreach = _FakeOutreachManager()
    crm = _FakeCRMService()
    agent = CampaignAgent(
        prospecting_svc=prospecting,
        outreach_mgr=outreach,
        crm_svc=crm,
        config_path=tmp_path / "daily_config.json",
    )
    cfg = agent.load_config()
    cfg["require_manual_approval"] = require_manual_approval
    cfg["daily_send_cap"] = 5
    agent.save_config(cfg)
    return agent, prospecting, outreach, crm


@pytest.mark.asyncio
async def test_manual_approval_default_is_true_on_fresh_config(tmp_path):
    agent, *_ = _agent(tmp_path)
    assert agent.load_config()["require_manual_approval"] is True


@pytest.mark.asyncio
async def test_run_new_prospects_with_manual_approval_does_not_send(tmp_path):
    results = [_qualified_result("r1", "Panaderia Ana"), _qualified_result("r2", "Taller Luis")]
    agent, prospecting, outreach, crm = _agent(tmp_path, results=results, require_manual_approval=True)

    report = await agent._run_new_prospects(agent.load_config())

    assert report["status"] == "pending_review"
    assert report["pending_review_count"] == 2
    assert outreach.launch_calls == []
    assert prospecting.mark_lead_stage_calls == []
    assert crm.sync_calls == []
    # Todo lo descubierto se sube al CRM igualmente, aunque no se contacte.
    assert prospecting.push_valid_calls == [("run-test-1", False)]
    # lead_stage sigue QUALIFIED — no se toca hasta que el humano decida.
    assert all(r["lead_stage"] == "QUALIFIED" for r in results)


@pytest.mark.asyncio
async def test_run_new_prospects_without_manual_approval_sends_as_before(tmp_path):
    results = [_qualified_result("r1", "Panaderia Ana")]
    agent, prospecting, outreach, crm = _agent(tmp_path, results=results, require_manual_approval=False)

    report = await agent._run_new_prospects(agent.load_config())

    assert report["status"] == "launched"
    assert report["sent_count"] == 1
    assert len(outreach.launch_calls) == 1
    assert prospecting.mark_lead_stage_calls == [("r1", "CONTACTED")]
    assert len(crm.sync_calls) == 1
    assert prospecting.push_valid_calls == [("run-test-1", False)]


@pytest.mark.asyncio
async def test_list_pending_review_filters_qualified_with_email(tmp_path):
    results = [
        _qualified_result("r1", "Con email"),
        {**_qualified_result("r2", "Sin email"), "email": ""},
    ]
    agent, *_ = _agent(tmp_path, results=results)

    pending = await agent.list_pending_review()

    assert [r["result_id"] for r in pending] == ["r1"]


@pytest.mark.asyncio
async def test_list_pending_review_excludes_plain_search_qualified_without_score(tmp_path):
    """lead_stage='QUALIFIED' tambien lo pone una busqueda normal de Sales
    (sin enriquecer) para cualquier resultado que pase el filtro basico —
    sin auditoria ni opportunity_score. La cola de campaña no debe mezclar
    eso con leads que de verdad pasaron el scoring de oportunidad."""
    real_campaign_lead = _qualified_result("r1", "Panaderia Ana")
    plain_sales_search_result = {
        **_qualified_result("r2", "Pagina de ayuda de HubSpot"),
        "opportunity_score": None,
        "technical_audit": None,
        "proposal": None,
    }
    agent, *_ = _agent(tmp_path, results=[real_campaign_lead, plain_sales_search_result])

    pending = await agent.list_pending_review()

    assert [r["result_id"] for r in pending] == ["r1"]


@pytest.mark.asyncio
async def test_send_to_prospect_launches_single_campaign_and_marks_contacted(tmp_path):
    results = [_qualified_result("r1", "Panaderia Ana"), _qualified_result("r2", "Taller Luis")]
    agent, prospecting, outreach, crm = _agent(tmp_path, results=results)

    result = await agent.send_to_prospect("r1")

    assert result["status"] == "sent"
    assert result["sent_count"] == 1
    assert len(outreach.launch_calls) == 1
    assert len(outreach.launch_calls[0]["prospects"]) == 1
    assert outreach.launch_calls[0]["prospects"][0]["company"] == "Panaderia Ana"
    assert prospecting.mark_lead_stage_calls == [("r1", "CONTACTED")]
    assert len(crm.sync_calls) == 1


@pytest.mark.asyncio
async def test_send_to_prospect_not_found_returns_not_found_status(tmp_path):
    agent, *_ = _agent(tmp_path, results=[])

    result = await agent.send_to_prospect("no-existe")

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_discard_prospect_marks_discarded_and_leaves_queue(tmp_path):
    results = [_qualified_result("r1", "Panaderia Ana")]
    agent, prospecting, *_ = _agent(tmp_path, results=results)

    result = await agent.discard_prospect("r1")

    assert result["status"] == "ok"
    assert results[0]["lead_stage"] == "DISCARDED"
    pending = await agent.list_pending_review()
    assert pending == []


@pytest.mark.asyncio
async def test_crm_feed_failure_does_not_break_the_run(tmp_path):
    """push_valid_to_crm fallando no debe tumbar el resto del ciclo — mismo
    criterio de resiliencia que el resto de pasos no criticos."""
    results = [_qualified_result("r1", "Panaderia Ana")]
    agent, prospecting, outreach, crm = _agent(tmp_path, results=results, require_manual_approval=True)

    async def _boom(run_id, *, dry_run=True):
        raise RuntimeError("CRM caido")

    prospecting.push_valid_to_crm = _boom

    report = await agent._run_new_prospects(agent.load_config())

    assert report["status"] == "pending_review"
    assert report["pending_review_count"] == 1
