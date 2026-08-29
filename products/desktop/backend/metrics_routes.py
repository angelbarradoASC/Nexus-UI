"""Métricas de Desktop: snapshot local, exposición Prometheus, ingesta interna.

`quick_action` vive aquí también — es otro endpoint interno gateado por
`require_desktop_internal`, no hay bastante volumen para justificar un
fichero propio solo para él.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger

from metrics import (
    metrics_response_body,
    metrics_response_content_type,
    update_collector_metrics,
    update_desktop_bridge_metrics,
    update_llm_router_metrics,
)
from products.desktop.backend.auth_routes import require_user
from products.desktop.backend.dependencies import require_desktop_internal

router = APIRouter()

_latest_metrics: dict[str, Any] = {}
_latest_alerts: list[dict[str, Any]] = []


@router.get("/api/metrics")
async def get_metrics(request: Request):
    require_user(request)
    return {"available": True, "metrics": _latest_metrics, "alerts": _latest_alerts}


@router.get("/metrics")
async def prometheus_metrics(request: Request) -> Response:
    from nexus.outreach.campaign_metrics import update_campaign_metrics

    runtime = getattr(request.app.state, "nexus_runtime", None)
    if runtime is not None:
        try:
            collectors = await runtime.coordinator.get_collector_status()
            update_collector_metrics(collectors)
        except Exception as exc:
            logger.warning("No se pudo refrescar metricas de recolectores | error={}", exc)

    llm_router = getattr(request.app.state, "llm_router", None)
    if llm_router is not None:
        try:
            update_llm_router_metrics(llm_router.metrics_snapshot())
        except Exception as exc:
            logger.warning("No se pudo refrescar metricas del router LLM | error={}", exc)

    if runtime is not None:
        try:
            await update_campaign_metrics(runtime.outreach._repository)
        except Exception as exc:
            logger.warning("No se pudo refrescar metricas de campañas | error={}", exc)

    update_desktop_bridge_metrics(_latest_metrics, _latest_alerts)
    return Response(content=metrics_response_body(), media_type=metrics_response_content_type())


@router.post("/api/metrics/ingest")
async def ingest_metrics(request: Request, _: None = Depends(require_desktop_internal)):
    global _latest_metrics, _latest_alerts
    body = await request.json()
    _latest_metrics = body.get("metrics", {})
    _latest_alerts = body.get("alerts", [])
    return {"status": "ok"}


@router.post("/api/quick-action")
async def quick_action(request: Request, _: None = Depends(require_desktop_internal)):
    body = await request.json()
    action = body.get("action", "")

    if action not in ("fichar_entrada", "fichar_salida"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Accion desconocida: {action}")

    task_id = str(uuid.uuid4())
    logger.info("Quick action aceptada en desktop | action={} | task_id={}", action, task_id)
    return {
        "status": "ok",
        "message": "Fichaje de entrada en proceso" if action == "fichar_entrada" else "Fichaje de salida en proceso",
        "task_id": task_id,
        "queued": False,
        "source": "desktop_backend",
        "timestamp": datetime.now().isoformat(),
    }
