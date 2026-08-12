"""
app/nexus/api/routes/campaign.py
-----------------------------------
Endpoints para gestionar y monitorizar la campaña diaria de prospección.

GET  /campaign/status          — estado del scheduler + último informe
GET  /campaign/config          — configuración de la campaña activa
PUT  /campaign/config          — actualizar configuración
POST /campaign/trigger         — lanzar ciclo ahora (trigger manual)
GET  /campaign/pending         — cola de revision humana (QUALIFIED sin
                                  contactar ni descartar aun)
POST /campaign/pending/{id}/send    — aprobar y enviar UN lead concreto
POST /campaign/pending/{id}/discard — descartar UN lead sin contactarlo
GET  /campaign/results         — leads de la ultima ejecucion (atajo sobre
                                  prospecting.list_results filtrado por run_id)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from nexus.api.dependencies.auth import get_campaign_agent, get_prospecting_manager
from nexus.prospecting import ProspectingAgentService
from nexus.prospecting.campaign_agent import CampaignAgent

router = APIRouter(prefix="/campaign", tags=["campaign"])


def _get_scheduler(request: Request):
    # El scheduler vive en app.state directamente (no en NexusRuntime) — su
    # ciclo de vida esta atado al lifespan de la app, igual que llm_router.
    return getattr(request.app.state, "nexus_scheduler", None)


@router.get("/status")
async def campaign_status(request: Request) -> dict[str, Any]:
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return {"status": "scheduler_not_initialized"}
    return {
        "status": "ok",
        "scheduler": scheduler.describe(),
    }


@router.get("/config")
async def campaign_config(agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    return {"status": "ok", "config": agent.load_config()}


@router.put("/config")
async def update_campaign_config(request: Request, agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    body = await request.json()
    current = agent.load_config()
    current.update({k: v for k, v in body.items() if k != "notes"})
    agent.save_config(current)
    return {"status": "ok", "config": current}


@router.post("/trigger")
async def trigger_campaign(request: Request) -> dict[str, Any]:
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return JSONResponse({"status": "error", "error": "scheduler_not_initialized"}, status_code=503)
    result = await scheduler.trigger_now()
    return {"status": "ok", "report": result}


@router.get("/pending")
async def campaign_pending(agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    """Leads QUALIFIED en cola de revision — nada se envia hasta que el
    usuario elija por cada uno via /pending/{result_id}/send."""
    pending = await agent.list_pending_review()
    return {"status": "ok", "total": len(pending), "pending": pending}


@router.post("/pending/{result_id}/send")
async def campaign_send_pending(result_id: str, agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    result = await agent.send_to_prospect(result_id)
    if result.get("status") == "not_found":
        return JSONResponse(result, status_code=404)
    return result


@router.post("/pending/{result_id}/discard")
async def campaign_discard_pending(result_id: str, agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    result = await agent.discard_prospect(result_id)
    if result.get("status") == "not_found":
        return JSONResponse(result, status_code=404)
    return result


@router.get("/results")
async def campaign_results(
    request: Request,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    """Atajo sobre prospecting.list_results con el run_id de la ultima ejecucion
    de campaña — evita que la UI tenga que leer el report del scheduler para
    sacar el run_id manualmente."""
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return JSONResponse({"status": "error", "error": "scheduler_not_initialized"}, status_code=503)
    report = (scheduler.describe() or {}).get("last_run_report") or {}
    run_id = (report.get("new_campaign") or {}).get("run_id")
    if not run_id:
        return {"status": "ok", "run_id": None, "results": []}
    payload = await prospecting.list_results(run_id=run_id)
    return {"status": "ok", "run_id": run_id, **payload}
