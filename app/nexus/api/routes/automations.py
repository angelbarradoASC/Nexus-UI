"""Automations route — disparo manual de workflows N8N."""

from __future__ import annotations

import httpx
from fastapi import APIRouter

router = APIRouter()

_N8N_BASE = "http://192.168.68.150:5678"
_N8N_AUTH = ("angel", "angel")

# Catálogo estático de automatizaciones expuestas al panel.
# Cada entrada puede tener un webhook_path (POST) o quedar como stub.
_AUTOMATIONS = [
    {
        "id":           "daily-prospecting-report",
        "name":         "Informe diario de prospección",
        "description":  "Genera y envía por email el resumen del día",
        "webhook_path": "/webhook/nexus-daily-report",
    },
    {
        "id":           "sync-crm-assets",
        "name":         "Sincronizar leads → CRM Assets",
        "description":  "Empuja los leads validados pendientes al CRM",
        "webhook_path": "/webhook/nexus-sync-crm",
    },
    {
        "id":           "cleanup-old-runs",
        "name":         "Limpiar runs antiguos",
        "description":  "Archiva runs de prospección con más de 30 días",
        "webhook_path": "/webhook/nexus-cleanup-runs",
    },
    {
        "id":           "warm-up-email",
        "name":         "Warm-up de email",
        "description":  "Ejecuta la secuencia de calentamiento de la cuenta",
        "webhook_path": "/webhook/nexus-email-warmup",
    },
]


@router.get("/automations")
async def list_automations() -> dict:
    return {"automations": _AUTOMATIONS}


@router.post("/automations/{automation_id}/trigger")
async def trigger_automation(automation_id: str) -> dict:
    entry = next((a for a in _AUTOMATIONS if a["id"] == automation_id), None)
    if entry is None:
        return {"status": "error", "detail": f"Automatización '{automation_id}' no encontrada"}

    webhook_path = entry.get("webhook_path")
    if not webhook_path:
        return {"status": "ok", "detail": "stub — sin webhook configurado", "automation_id": automation_id}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_N8N_BASE}{webhook_path}",
                auth=_N8N_AUTH,
                json={"source": "nexus-sales-panel", "automation_id": automation_id},
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"status": "error", "detail": f"N8N respondió {e.response.status_code}"}
    except httpx.RequestError as e:
        return {"status": "error", "detail": f"N8N no disponible: {e}"}

    return {"status": "ok", "automation_id": automation_id}
