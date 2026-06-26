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
from nexus.prompts import resolve_prompt_sync
from nexus.prospecting import ProspectingAgentService
from nexus.prospecting.models import normalize_vertical

router = APIRouter()

_INTERPRET_SYSTEM = """Extract B2B prospecting parameters from Spanish text. Output ONLY valid JSON. No explanation. No markdown. No commentary.

Example input: "busca asesorias fiscales en Toledo, unas 30, para Automato"
Example output: {"vertical":"asesoria","target_description":"asesorias fiscales","city":"Toledo","province":"Toledo","region":"","desired_count":30,"minimum_score":40,"represented_by":"automato","must_have":[],"dry_run":true}

Example input: "cerca de parla en un radio de 20 km, asesorias"
Example output: {"vertical":"asesoria","target_description":"asesorias","city":"Parla","province":"Madrid","region":"","desired_count":20,"minimum_score":40,"represented_by":"assets","must_have":[],"dry_run":true}

Example input: "clinicas dentales en la zona de madrid sur cerca de parla"
Example output: {"vertical":"salud","target_description":"clinicas dentales","city":"Parla","province":"Madrid","region":"","desired_count":20,"minimum_score":40,"represented_by":"assets","must_have":[],"dry_run":true}

Rules:
- represented_by: "automato" if text mentions automato/Automato, else "assets"
- vertical: "asesoria" for asesor/gestor/fiscal/laboral/contable; "salud" for clinica/dentista/odontologia/salud; "inmobiliaria" for pisos/alquiler/agencia; "public_administration" for ayuntamiento/municipio; "restaurants" for restaurante/hosteleria; if none fits, create a short snake_case vertical instead de custom
- desired_count: extract number if mentioned, else 20
- dry_run: true unless user says "real" or "lanzar de verdad"
- ALWAYS capitalize proper nouns: city and province names (parla→Parla, toledo→Toledo, madrid→Madrid)
- Extract city and province from context; infer province from well-known cities when not explicit"""


class InterpretRequest(BaseModel):
    text: str


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
    elif any(w in t for w in ("clinica", "clínica", "dentista", "odont", "odontologia", "odontología", "salud")):
        vertical = "salud"
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
    count_match = re.search(r"\b(unas?\s*)?(\d+)\s*(empresa|lead|result|negocio|unas?)", t)
    desired_count = int(count_match.group(2)) if count_match else 20

    stop_lower = {
        "quiero", "busca", "buscar", "dame", "encuentra", "en", "de", "por", "con",
        "cerca", "radio", "provincia", "zona", "sur", "norte", "este", "oeste",
        "la", "el", "los", "las", "un", "una", "unos", "como", "unas", "para",
        "que", "hay", "del", "al", "se", "fiscal", "laboral", "contable",
    }

    # 1. Palabras después de preposiciones de lugar (captura minúsculas también)
    prep_hits = re.findall(
        r'\b(?:en|cerca de|en la ciudad de|ciudad de|municipio de|en el municipio de)\s+'
        r'([a-záéíóúña-z][a-záéíóúña-zA-ZÁÉÍÓÚÑ]*(?:\s+[a-záéíóúña-zA-ZÁÉÍÓÚÑ]+)?)',
        text, re.IGNORECASE,
    )
    # 2. Palabras capitalizadas directamente en el texto original
    cap_hits = re.findall(r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})\b', text)

    # Unir, capitalizar y filtrar palabras de parada
    seen: list[str] = []
    for raw in prep_hits + cap_hits:
        normalized = raw.strip().title()  # "parla" → "Parla", "La Parla" → "La Parla"
        if normalized.lower() not in stop_lower and normalized not in seen and len(normalized) > 2:
            seen.append(normalized)

    city     = seen[0] if seen else ""
    province = seen[1] if len(seen) > 1 else ""

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
        "target_description": text[:120],
        "_fallback": True,
    }


def _sanitize_vertical_from_text(brief: dict, text: str) -> dict:
    # La interpretación ya no debe inferir vertical: la UI la decide si hace falta.
    brief["vertical"] = "custom"
    brief["vertical_created"] = False
    return brief


@router.post("/prospecting/interpret")
async def interpret_brief(
    payload: InterpretRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    """Interpreta texto libre y devuelve parámetros de prospección."""
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    llm = get_router()
    response = await llm.call(
        messages=[
            {"role": "system", "content": resolve_prompt_sync("sales.prospecting.interpret")},
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

    brief = _sanitize_vertical_from_text(brief, payload.text)
    brief["vertical"] = "custom"
    brief["vertical_created"] = False
    brief.setdefault("desired_count", 20)
    brief.setdefault("minimum_score", 40)
    brief.setdefault("represented_by", "assets")
    brief.setdefault("dry_run", True)
    brief.setdefault("must_have", [])
    orchestrated = await prospecting.orchestrate_brief(brief, original_text=payload.text.strip())
    return {
        "status": "ok",
        "brief": orchestrated["brief"],
        "orchestration": orchestrated["orchestration"],
    }


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
