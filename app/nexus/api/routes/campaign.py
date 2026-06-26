"""
app/nexus/api/routes/campaign.py
-----------------------------------
Endpoints para gestionar y monitorizar la campaña diaria de prospección.

GET  /campaign/status          — estado del scheduler + último informe
GET  /campaign/config          — configuración de la campaña activa
PUT  /campaign/config          — actualizar configuración
POST /campaign/trigger         — lanzar ciclo ahora (trigger manual)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/campaign", tags=["campaign"])


def _get_scheduler(request: Request):
    return getattr(request.app.state, "nexus_scheduler", None)


def _get_campaign_agent(request: Request):
    return getattr(request.app.state, "campaign_agent", None)


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
async def campaign_config(request: Request) -> dict[str, Any]:
    agent = _get_campaign_agent(request)
    if agent is None:
        return JSONResponse({"status": "error", "error": "campaign_agent_not_initialized"}, status_code=503)
    return {"status": "ok", "config": agent.load_config()}


@router.put("/config")
async def update_campaign_config(request: Request) -> dict[str, Any]:
    agent = _get_campaign_agent(request)
    if agent is None:
        return JSONResponse({"status": "error", "error": "campaign_agent_not_initialized"}, status_code=503)
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
