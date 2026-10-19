"""
app/nexus/api/routes/campaign.py
-----------------------------------
Endpoints para gestionar y monitorizar la campaña diaria de prospección.

GET  /campaign/status          — estado del scheduler + último informe
GET  /campaign/accounts        — cuentas reales de envío disponibles (Thunderbird)
GET  /campaign/config          — configuración de la campaña activa
PUT  /campaign/config          — actualizar configuración (línea concreta, ver "line")
PUT  /campaign/global-toggle   — pausar/activar TODO el ciclo diario (todas las líneas)
POST /campaign/trigger         — lanzar ciclo ahora (trigger manual)
GET  /campaign/pending         — cola de revision humana (QUALIFIED sin
                                  contactar ni descartar aun)
POST /campaign/pending/{id}/send    — aprobar y enviar UN lead concreto
POST /campaign/pending/{id}/discard — descartar UN lead sin contactarlo
GET  /campaign/results         — leads de la ultima ejecucion (atajo sobre
                                  prospecting.list_results filtrado por run_id)
POST /campaign/decompose-verify — descompone una peticion en lenguaje
                                  natural y la verifica de ida y vuelta
                                  contra el LLM local (ver
                                  nexus.prospecting.campaign_decompose)
GET/PUT/DELETE /campaign/offerings[/{slug}] y POST .../toggle — catalogo de
                                  lo que ofrece Assets (encaje del analisis)
POST /campaign/analyze-fit     — analiza UNA empresa y busca su encaje con Assets
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_campaign_agent, get_campaign_decomposer, get_prospecting_manager
from nexus.prospecting import ProspectingAgentService
from nexus.prospecting.campaign_agent import CampaignAgent
from nexus.prospecting.campaign_decompose import CampaignDecomposer

router = APIRouter(prefix="/campaign", tags=["campaign"])


class _DecomposeVerifyRequest(BaseModel):
    text: str


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


@router.get("/accounts")
async def campaign_accounts(agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    """Cuentas reales de envio disponibles (extraidas de Thunderbird) para
    poblar el selector de "Cuenta de envío" en la UI — nunca texto libre."""
    return {"status": "ok", "accounts": agent.outreach.list_accounts()}


@router.get("/config")
async def campaign_config(agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    return {"status": "ok", "config": agent.load_config()}


@router.put("/config")
async def update_campaign_config(request: Request, agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    """Actualiza UNA linea de campaña — "default" (el dict plano de
    siempre) o una entrada de additional_campaigns por su "name". El
    cuerpo lleva el propio campo "line" (opcional, default "default") mas
    los campos a actualizar de esa linea — nunca se mezclan lineas
    distintas en un solo PUT."""
    body = await request.json()
    line = body.pop("line", "default") or "default"
    updates = {k: v for k, v in body.items() if k not in ("notes", "line")}

    current = agent.load_config()
    if line == "default":
        current.update(updates)
    else:
        extras = current.setdefault("additional_campaigns", [])
        target = next((e for e in extras if e.get("name") == line), None)
        if target is None:
            return JSONResponse({"status": "not_found", "line": line}, status_code=404)
        target.update(updates)

    agent.save_config(current)
    return {"status": "ok", "config": current}


@router.put("/global-toggle")
async def update_campaign_global_toggle(request: Request, agent: CampaignAgent = Depends(get_campaign_agent)) -> dict[str, Any]:
    """Interruptor GLOBAL — para TODO el ciclo diario, follow-ups incluidos,
    de todas las lineas. Deliberadamente separado de pausar una linea
    concreta (PUT /config con default_enabled o enabled por linea) para
    que un operador no pare sin querer los follow-ups de leads ya
    contactados al pausar solo una via."""
    body = await request.json()
    current = agent.load_config()
    current["enabled"] = bool(body.get("enabled", True))
    agent.save_config(current)
    return {"status": "ok", "enabled": current["enabled"]}


@router.post("/trigger")
async def trigger_campaign(request: Request) -> dict[str, Any]:
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return JSONResponse({"status": "error", "error": "scheduler_not_initialized"}, status_code=503)
    result = await scheduler.trigger_now()
    return {"status": "ok", "report": result}


@router.get("/pending")
async def campaign_pending(
    track: str | None = None,
    agent: CampaignAgent = Depends(get_campaign_agent),
) -> dict[str, Any]:
    """Leads QUALIFIED en cola de revision — nada se envia hasta que el
    usuario elija por cada uno via /pending/{result_id}/send.

    track filtra por vertical/linea de campaña (ej. ?track=ia_adopcion) —
    dos colas de revision separadas para las vias IA/OT; sin track devuelve
    todas juntas (comportamiento previo, sigue igual para quien no lo use)."""
    pending = await agent.list_pending_review(vertical=track)
    return {"status": "ok", "total": len(pending), "pending": pending, "track": track}


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
    """Atajo sobre prospecting.list_results con los run_id de la ultima
    ejecucion de campaña — evita que la UI tenga que leer el report del
    scheduler para sacarlos a mano. Junta los resultados de TODAS las
    lineas que corrieron ese dia (report['campaigns']), no solo una —
    antes usaba report['new_campaign'] (una sola linea, la de siempre),
    que escondia en silencio los resultados de cualquier otra linea activa
    el mismo dia."""
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return JSONResponse({"status": "error", "error": "scheduler_not_initialized"}, status_code=503)
    report = (scheduler.describe() or {}).get("last_run_report") or {}
    campaigns = report.get("campaigns") or {}
    run_ids = sorted({v.get("run_id") for v in campaigns.values() if v.get("run_id")})
    if not run_ids:
        return {"status": "ok", "run_ids": [], "results": []}

    merged: list[dict[str, Any]] = []
    for run_id in run_ids:
        payload = await prospecting.list_results(run_id=run_id)
        merged.extend(payload.get("results") or [])
    return {"status": "ok", "run_ids": run_ids, "results": merged}


@router.post("/decompose-verify")
async def campaign_decompose_verify(
    payload: _DecomposeVerifyRequest,
    decomposer: CampaignDecomposer = Depends(get_campaign_decomposer),
) -> dict[str, Any]:
    """Descompone `text` en {vertical, business_type, city, radius_km} y
    verifica de ida y vuelta contra el LLM local — ver
    nexus.prospecting.campaign_decompose.CampaignDecomposer."""
    return await decomposer.decompose_and_verify(payload.text)


# ── Catalogo de ayudas/subvenciones ──────────────────────────────────────────
# Pedido explicito del usuario: la propia campaña debe mantener su catalogo
# de ayudas fresco (que sigue vigente, que ha caducado, que hay nuevo) — ver
# nexus.prospecting.grants_discovery.GrantsDiscoveryService.

@router.get("/grants")
async def list_grants(
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    """Catalogo completo (activas, pendientes de revision y expiradas) —
    la UI distingue por el campo 'estado' de cada una."""
    grants = prospecting.grants.list_all()
    return {"status": "ok", "total": len(grants), "grants": [g.to_dict() for g in grants]}


@router.post("/grants/refresh")
async def refresh_grants(
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    """Dispara la comprobacion de vigencia + busqueda de ayudas nuevas.
    Las nuevas entran como pendiente_revision — nunca se activan solas."""
    return await prospecting.refresh_grants_catalog()


@router.post("/grants/{slug}/approve")
async def approve_grant(
    slug: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    """Aprueba una ayuda descubierta automaticamente — pasa a activa y
    empieza a influir en la clasificacion de leads a partir de ahora."""
    grant = prospecting.grants.set_estado(slug, "activo")
    if grant is None:
        return JSONResponse({"status": "not_found", "slug": slug}, status_code=404)
    return {"status": "ok", "grant": grant.to_dict()}


@router.post("/grants/{slug}/reject")
async def reject_grant(
    slug: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    """Descarta una ayuda descubierta automaticamente que no era real/no
    aplica — se borra, a diferencia de 'expirado' (que si fue real)."""
    grant = prospecting.grants.get(slug)
    if grant is None:
        return JSONResponse({"status": "not_found", "slug": slug}, status_code=404)
    if grant.fuente == "semilla_inicial":
        return JSONResponse(
            {"status": "error", "error": "No se puede rechazar una ayuda de la semilla inicial — usa expirar en su lugar."},
            status_code=400,
        )
    prospecting.grants.delete(slug)
    return {"status": "ok", "slug": slug}


# ── Catalogo de lo que ofrece Assets Consultores ─────────────────────────────
# Lo que el analisis de una empresa consulta para buscar ENCAJE real — ver
# nexus.prospecting.offerings. Curado a mano, editable aqui y en Configuracion.

class _OfferingBody(BaseModel):
    nombre: str
    tipo: str = "servicio"
    descripcion: str = ""
    senales: list[str] = []
    normativas: list[str] = []
    sectores: list[str] = []
    cautelas: str = ""
    url: str = ""
    activo: bool = True


@router.get("/offerings")
async def list_offerings(
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    offerings = prospecting.offerings.list_all()
    return {"status": "ok", "total": len(offerings), "offerings": [o.to_dict() for o in offerings]}


@router.put("/offerings/{slug}")
async def upsert_offering(
    slug: str,
    body: _OfferingBody,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    offering = prospecting.offerings.upsert(slug=slug.strip(), **body.model_dump())
    return {"status": "ok", "offering": offering.to_dict()}


@router.post("/offerings/{slug}/toggle")
async def toggle_offering(
    slug: str,
    request: Request,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    body = await request.json()
    offering = prospecting.offerings.set_activo(slug, bool(body.get("activo", True)))
    if offering is None:
        return JSONResponse({"status": "not_found", "slug": slug}, status_code=404)
    return {"status": "ok", "offering": offering.to_dict()}


@router.delete("/offerings/{slug}")
async def delete_offering(
    slug: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    if prospecting.offerings.get(slug) is None:
        return JSONResponse({"status": "not_found", "slug": slug}, status_code=404)
    prospecting.offerings.delete(slug)
    return {"status": "ok", "slug": slug}


# ── Analisis de encaje de UNA empresa ────────────────────────────────────────

class _AnalyzeFitBody(BaseModel):
    website: str
    name: str = ""
    extra_context: str = ""


@router.post("/analyze-fit")
async def analyze_company_fit(
    body: _AnalyzeFitBody,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict[str, Any]:
    """Analiza una empresa concreta (web, auditoria, perfil) y busca su
    encaje con lo que ofrece Assets — ver ProspectingAgentService.
    analyze_company_fit. extra_context es informacion ya verificada por una
    persona (registro, noticias...) que se suma a lo que sale de la web."""
    result = await prospecting.analyze_company_fit(
        website=body.website, name=body.name, extra_context=body.extra_context,
    )
    if result.get("status") == "error":
        return JSONResponse(result, status_code=400)
    return result
