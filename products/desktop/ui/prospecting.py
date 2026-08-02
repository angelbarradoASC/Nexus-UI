"""Generalized prospecting routes for Nexus Sales."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from agents.llm_router import get_router
from nexus.api.dependencies.auth import get_prospecting_manager
from nexus.api.schemas.prospecting import (
    ProspectingDiscardedListResponse,
    ProspectingPushRequest,
    ProspectingPushResponse,
    ProspectingResultListResponse,
    ProspectingRunDetailResponse,
    ProspectingRunRequest,
    ProspectingRunResponse,
)
from nexus.prospecting.models import normalize_vertical
from nexus.prospecting import ProspectingAgentService
router = APIRouter()

_INTERPRET_SYSTEM = """Extract B2B prospecting parameters from Spanish text. Output ONLY valid JSON. No explanation. No markdown. No commentary.

Example input: "busca asesorias fiscales en Toledo, unas 30, para Automato"
Example output: {"vertical":"asesoria","target_description":"asesorias fiscales","city":"Toledo","province":"Toledo","region":"","desired_count":30,"minimum_score":40,"represented_by":"automato","must_have":[],"dry_run":true}

Rules:
- represented_by: "automato" if text mentions automato/Automato, else "assets"
- vertical: "asesoria" for asesor/gestor/fiscal/laboral/contable; "salud" for clinica/dentista/odontologia/salud; "inmobiliaria" for pisos/alquiler/agencia; "public_administration" for ayuntamiento/municipio; "restaurants" for restaurante/hosteleria; if none fits, create a short snake_case vertical instead of custom
- desired_count: extract number if mentioned, else 20
- dry_run: true unless user says "real" or "lanzar de verdad"
- Extract city and province literally from user text"""


_CHAT_SYSTEM = """Eres un asistente de prospección B2B en español. Ayudas al usuario a especificar qué quiere buscar para lanzar una búsqueda automatizada.

CAMPOS NECESARIOS:
- vertical: "asesoria" (asesor/gestor/fiscal/laboral/contable), "salud" (clinica/dentista), "inmobiliaria" (pisos/agencia), "restaurants" (restaurante/hosteleria/bar), "public_administration" (ayuntamiento/municipio), o un slug snake_case custom
- city: ciudad concreta (OBLIGATORIO — pregunta esto primero si falta)
- province: provincia (déjala igual que city si no se menciona)
- region: comunidad autónoma (puede quedar vacío)
- target_description: frase breve de lo que busca
- desired_count: número de resultados (por defecto 20)
- minimum_score: umbral 0-100 (por defecto 40)
- represented_by: "assets" (por defecto) o "automato" si se menciona
- must_have: lista de requisitos ["Email directo", "Teléfono", "Web propia", "Dirección física"]
- dry_run: true por defecto; false solo si el usuario dice explícitamente "real" o "lanzar de verdad"

REGLAS:
1. Si no tienes city, PREGÚNTALA primero. Es el campo más crítico.
2. Haz solo UNA pregunta a la vez.
3. Cuando tengas city y vertical, ya puedes confirmar con status=ready.
4. Sé natural y directo. Sin listas de puntos en el reply.
5. SIEMPRE responde con JSON válido, sin texto fuera del JSON.

RESPUESTA cuando necesitas más información:
{"status": "clarifying", "reply": "Pregunta natural y breve."}

RESPUESTA cuando tienes lo suficiente para lanzar:
{"status": "ready", "reply": "Resumen breve de lo que vas a buscar.", "brief": {"vertical":"asesoria","city":"Toledo","province":"Toledo","region":"Castilla-La Mancha","target_description":"asesorias fiscales con email","desired_count":20,"minimum_score":40,"represented_by":"assets","must_have":["Email directo"],"dry_run":true}}"""


class InterpretRequest(BaseModel):
    text: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


def _normalize_text(value: str) -> str:
    import unicodedata

    raw = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = raw.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())

def _fallback_parse(text: str) -> dict:
    """Reglas heurísticas si el LLM no devuelve JSON válido."""
    t = text.lower()

    if any(w in t for w in ("asesor", "gestor", "fiscal", "laboral", "contable")):
        vertical = "asesoria"
    elif any(w in t for w in ("inmobiliaria", "agencia inmob", "pisos", "alquiler", "vivienda")):
        vertical = "inmobiliaria"
    elif any(w in t for w in ("ayuntamiento", "municipio", "administración", "concejal")):
        vertical = "public_administration"
    elif any(w in t for w in ("restaurante", "hostelería", "bar ", "cafetería")):
        vertical = "restaurants"
    else:
        vertical = normalize_vertical("custom", fallback_text=text)

    represented_by = "automato" if "automato" in t else "assets"

    # Número de resultados: "unas 20", "30 empresas", etc.
    count_match = re.search(r"\b(unas?\s*|busca\s*)?(\d+)\s*(empresa|lead|result|negocio)", t)
    desired_count = int(count_match.group(2)) if count_match else 20

    # Ciudad/provincia: última palabra en mayúscula antes de preposición común
    # Búsqueda simple: palabras con inicial mayúscula en el texto original
    capitalized = re.findall(r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)\b', text)
    # Filtrar palabras comunes que empiezan en mayúscula
    stop = {"Quiero", "Busca", "Buscar", "Dame", "Encuentra", "En", "De", "Por", "Con",
            "Cerca", "Radio", "Provincia", "Zona", "Sur", "Norte", "Este", "Oeste",
            "La", "El", "Los", "Las", "Un", "Una", "Unos"}
    locations = [w for w in capitalized if w not in stop]
    city = locations[0] if locations else ""
    province = locations[1] if len(locations) > 1 else ""

    return {
        "vertical": vertical,
        "represented_by": represented_by,
        "city": city,
        "province": province,
        "region": "",
        "desired_count": desired_count,
        "minimum_score": 40,
        "dry_run": True,
        "must_have": [],
        "target_description": "",
        "_fallback": True,
    }


@router.post("/prospecting/interpret")
async def interpret_brief(payload: InterpretRequest) -> dict:
    """Interpreta texto libre y devuelve parámetros de prospección."""
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    llm = get_router()
    response = await llm.call(
        messages=[
            {"role": "system", "content": _INTERPRET_SYSTEM},
            {"role": "user", "content": payload.text.strip()},
        ],
        preferred_level=1,   # L1 con few-shot; fallback por reglas si falla
        temperature=0.1,
        max_tokens=600,
    )

    brief = None

    if not response.error:
        raw = (response.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end >= start:
            raw = raw[start : end + 1]
        try:
            brief = json.loads(raw)
        except Exception:
            brief = None

    # Fallback por reglas si el LLM falla o devuelve basura
    if brief is None:
        brief = _fallback_parse(payload.text)

    brief["vertical"] = "custom"
    brief["vertical_created"] = False
    brief.setdefault("desired_count", 20)
    brief.setdefault("minimum_score", 40)
    brief.setdefault("represented_by", "assets")
    brief.setdefault("dry_run", True)
    brief.setdefault("must_have", [])

    return {"status": "ok", "brief": brief}


def _parse_llm_json(raw: str) -> dict | None:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e >= s:
        try:
            return json.loads(raw[s : e + 1])
        except Exception:
            pass
    return None


@router.post("/prospecting/chat")
async def prospecting_chat(
    payload: ChatRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    """Motor conversacional: extrae intención, aclara dudas y valida empíricamente antes de confirmar."""
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    history.append({"role": "user", "content": payload.message})

    llm = get_router()
    response = await llm.call(
        messages=[{"role": "system", "content": _CHAT_SYSTEM}, *history],
        preferred_level=1,
        temperature=0.2,
        max_tokens=700,
    )

    parsed = None
    if not response.error:
        parsed = _parse_llm_json(response.content or "")

    if not parsed:
        return {
            "status": "clarifying",
            "reply": "No entendí bien. ¿Puedes describir qué tipo de negocio buscas y en qué ciudad?",
        }

    status = parsed.get("status", "clarifying")
    reply = str(parsed.get("reply", ""))
    brief = parsed.get("brief")

    # Probe empírico cuando el LLM dice que ya tiene suficiente
    if status == "ready" and brief and brief.get("city"):
        probe = await prospecting.quick_probe(
            city=brief["city"],
            vertical=brief.get("vertical", ""),
        )
        if probe.get("quality") == "empty":
            city = brief.get("city", "")
            vertical_label = brief.get("vertical", "").replace("_", " ")
            status = "clarifying"
            reply = (
                f"He hecho una búsqueda rápida de {vertical_label} en {city} "
                f"y no encontré resultados reales. "
                f"¿Estás seguro de la ubicación o del tipo de negocio?"
            )
            brief = None
        elif probe.get("quality") == "sparse":
            reply += f" La zona tiene pocos resultados en abierto — puede que el run sea corto."

    if status == "ready" and brief:
        brief.setdefault("province", brief.get("city", ""))
        brief.setdefault("region", "")
        brief.setdefault("target_description", "")
        brief.setdefault("desired_count", 20)
        brief.setdefault("minimum_score", 40)
        brief.setdefault("represented_by", "assets")
        brief.setdefault("must_have", [])
        brief.setdefault("dry_run", True)

    return {"status": status, "reply": reply, "brief": brief}


@router.post("/prospecting/run", response_model=ProspectingRunResponse)
async def run_prospecting(
    payload: ProspectingRunRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingRunResponse:
    return await prospecting.run(payload.model_dump())


@router.post("/prospecting/runs/{run_id}/resume", response_model=ProspectingRunResponse)
async def resume_prospecting(
    run_id: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingRunResponse:
    result = await prospecting.resume_run(run_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return result


@router.get("/prospecting/api-budget")
async def get_api_budget(
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    """Current month's Google Places API call budget status."""
    return prospecting.get_budget()


@router.get("/prospecting/runs/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    level: str | None = Query(default=None, description="Filtrar por nivel: info, warning, error"),
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    """Devuelve el log estructurado de eventos de un run."""
    result = await prospecting.get_run(run_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    logs = result.get("logs") or []
    if level:
        logs = [entry for entry in logs if entry.get("level") == level]
    return {
        "run_id": run_id,
        "status": result.get("status"),
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "total": len(logs),
        "logs": logs,
    }


@router.get("/prospecting/runs/{run_id}", response_model=ProspectingRunDetailResponse)
async def get_run(
    run_id: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingRunDetailResponse:
    result = await prospecting.get_run(run_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return result


@router.get("/prospecting/results", response_model=ProspectingResultListResponse)
async def list_results(
    run_id: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    crm_state: str | None = Query(default=None),
    vertical: str | None = Query(default=None),
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingResultListResponse:
    return await prospecting.list_results(run_id=run_id, min_score=min_score, crm_state=crm_state, vertical=vertical)


@router.get("/prospecting/discarded", response_model=ProspectingDiscardedListResponse)
async def list_discarded(
    run_id: str | None = Query(default=None),
    vertical: str | None = Query(default=None),
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingDiscardedListResponse:
    return await prospecting.list_discarded(run_id=run_id, vertical=vertical)


@router.post("/prospecting/results/{result_id}/push-to-crm", response_model=ProspectingPushResponse)
async def push_result_to_crm(
    result_id: str,
    payload: ProspectingPushRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingPushResponse:
    response = await prospecting.push_result_to_crm(result_id, dry_run=payload.dry_run)
    if response.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Result {result_id} not found")
    return response


@router.post("/prospecting/push-valid-to-crm", response_model=ProspectingPushResponse)
async def push_valid_results_to_crm(
    payload: ProspectingPushRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingPushResponse:
    if not payload.run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    response = await prospecting.push_valid_to_crm(payload.run_id, dry_run=payload.dry_run)
    if response.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Run {payload.run_id} not found")
    return response


# Backward-compatible aliases while the UI settles.
@router.post("/prospecting/municipal/run", response_model=ProspectingRunResponse)
async def run_municipal_alias(
    payload: ProspectingRunRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingRunResponse:
    return await prospecting.run(payload.model_dump())


@router.get("/prospecting/municipal/runs/{run_id}", response_model=ProspectingRunDetailResponse)
async def get_municipal_run_alias(
    run_id: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingRunDetailResponse:
    return await get_run(run_id, prospecting)


@router.get("/prospecting/municipal/results", response_model=ProspectingResultListResponse)
async def list_municipal_results_alias(
    run_id: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    crm_state: str | None = Query(default=None),
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingResultListResponse:
    return await prospecting.list_results(run_id=run_id, min_score=min_score, crm_state=crm_state, vertical="public_administration")


@router.get("/prospecting/municipal/discarded", response_model=ProspectingDiscardedListResponse)
async def list_municipal_discarded_alias(
    run_id: str | None = Query(default=None),
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingDiscardedListResponse:
    return await prospecting.list_discarded(run_id=run_id, vertical="public_administration")


@router.post("/prospecting/municipal/results/{result_id}/push-to-crm", response_model=ProspectingPushResponse)
async def push_municipal_result_to_crm_alias(
    result_id: str,
    payload: ProspectingPushRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingPushResponse:
    return await push_result_to_crm(result_id, payload, prospecting)


@router.post("/prospecting/municipal/push-valid-to-crm", response_model=ProspectingPushResponse)
async def push_valid_municipal_results_to_crm_alias(
    payload: ProspectingPushRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingPushResponse:
    return await push_valid_results_to_crm(payload, prospecting)
