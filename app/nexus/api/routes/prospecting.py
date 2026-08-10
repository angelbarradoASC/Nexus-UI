"""Generalized prospecting routes for Nexus Sales."""

from __future__ import annotations

import asyncio
import inspect
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
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
from nexus.prospecting.sales_verticals import (
    DuplicateVerticalError,
    ProtectedVerticalError,
    VerticalNotFoundError,
)
from nexus.utils.llm_json import parse_llm_json
from nexus.utils.text import normalize_text

router = APIRouter()

# System prompts live in nexus/prompts/catalogue.py:
#   interpret → "sales.prospecting.interpret"
#   chat      → "sales.prospecting.chat"


class InterpretRequest(BaseModel):
    text: str


# Mismo mecanismo que el bucle de PEPO (desktop/local_agents/system_task_agent.py):
# tool calling forzado en vez de "pedir JSON en texto y esperar" — mas robusto con
# modelos de razonamiento (el contenido de razonamiento no puede corromper el JSON
# si la respuesta estructurada va en tool_calls, no en content).
_INTERPRET_BRIEF_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "set_prospecting_brief",
            "description": "Estructura los parametros de prospeccion B2B extraidos del texto libre del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vertical": {
                        "type": "string",
                        "description": (
                            "Usa EXACTAMENTE uno de los slugs listados en 'VERTICALES DISPONIBLES' "
                            "del contexto de este mensaje. Nunca inventes un slug nuevo — si ninguno "
                            "encaja de verdad, usa 'custom'."
                        ),
                    },
                    "target_description": {
                        "type": "string",
                        "description": (
                            "SOLO el sintagma nominal que describe el tipo de negocio, "
                            "ej. 'restaurantes de lujo', 'asesorias fiscales'. NUNCA copies la frase completa "
                            "del usuario ni incluyas verbos de instruccion (quiero que, busca, dame...) "
                            "ni la geografia ni la marca representada."
                        ),
                    },
                    "city": {
                        "type": "string",
                        "description": (
                            "SOLO el nombre propio de la ciudad/localidad, capitalizado (ej. 'Salamanca', 'Toledo'). "
                            "Si el texto dice 'la zona de X' o 'cerca de X', la ciudad es X, nunca la palabra 'zona'."
                        ),
                    },
                    "province": {
                        "type": "string",
                        "description": "SOLO el nombre propio de la provincia. Nunca la marca representada (ej. 'Automato', 'Assets') ni un verbo.",
                    },
                    "region": {"type": "string"},
                    "radius_km": {
                        "type": "integer",
                        "description": (
                            "SOLO si el usuario menciona explicitamente un radio o distancia "
                            "('en un radio de 20km', 'a menos de 15km de X'). Numero en kilometros, "
                            "entre 1 y 250. Si no lo menciona, omite este campo."
                        ),
                    },
                    "desired_count": {"type": "integer"},
                    "represented_by": {"type": "string", "enum": ["assets", "automato", "other"]},
                    "must_have": {"type": "array", "items": {"type": "string"}},
                    "min_employees": {"type": "integer"},
                    "max_employees": {"type": "integer"},
                    "industrial_zone": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                "required": ["vertical", "target_description", "city"],
            },
        },
    }
]


class ChatMessage(BaseModel):
    role: str
    content: str


class ProspectingChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


def _fallback_parse(text: str, verticals) -> dict:
    """Reglas heurísticas si el LLM no devuelve JSON válido."""
    t = normalize_text(text)

    # Resuelve el vertical contra nombre+aliases de las verticales ACTIVAS en
    # BBDD — nunca un catalogo hardcodeado. Cae a 'custom' si nada encaja.
    vertical = verticals.resolve(fallback_text=text).slug

    represented_by = "automato" if "automato" in t else "assets"

    # Número de resultados: "unas 20", "30 empresas", etc.
    count_match = re.search(r"\b(unas?\s*)?(\d+)\s*(empresa|lead|result|negocio|unas?)", t)
    desired_count = int(count_match.group(2)) if count_match else 20

    # Rango de empleados: "de 30 a 50 empleados", "entre 10 y 50 empleados"
    emp_match = re.search(
        r"(?:de\s+|entre\s+)(\d+)\s+(?:a|y)\s+(\d+)\s+empleados?",
        t,
    )
    min_employees: int | None = None
    max_employees: int | None = None
    if emp_match:
        min_employees = int(emp_match.group(1))
        max_employees = int(emp_match.group(2))
    else:
        single_emp = re.search(r"(\d+)\s+empleados?", t)
        if single_emp:
            max_employees = int(single_emp.group(1))

    # Radio: "en un radio de 20km", "a menos de 15 km", "20km a la redonda"
    radius_match = re.search(r"radio\s+de\s+(\d+)\s*km|(?:a\s+)?(\d+)\s*km(?:\s+a\s+la\s+redonda)?", t)
    radius_km: int | None = None
    if radius_match:
        radius_km = int(radius_match.group(1) or radius_match.group(2))

    # Zona industrial: "polígono de Malpica", "polígono Malpica", "pol. industrial Malpica"
    poligono_match = re.search(
        r"pol[ií]gono(?:\s+(?:industrial|ind\.?|de))?\s+(?:de\s+)?([a-zà-ü]{3,})",
        t,
    )
    industrial_zone = poligono_match.group(1).title() if poligono_match else ""

    # Must-have: contacto requerido
    must_have: list[str] = []
    if any(w in t for w in ("correo", "email", "e-mail", "mail")):
        must_have.append("email")
    if any(w in t for w in ("telefono", "tlf", "movil", "whatsapp")):
        must_have.append("telefono")

    stop_lower = {
        "quiero", "busca", "buscar", "dame", "encuentra", "en", "de", "por", "con",
        "cerca", "radio", "provincia", "zona", "sur", "norte", "este", "oeste",
        "la", "el", "los", "las", "un", "una", "unos", "como", "unas", "para",
        "que", "hay", "del", "al", "se", "fiscal", "laboral", "contable",
        "poligono", "industrial", "ind",
    }

    # Si hay polígono, forzar ciudad = nombre del polígono y buscar provincia en el texto
    if industrial_zone:
        city = industrial_zone
        # Buscar la ciudad/provincia real: primer topónimo capitalizado que no sea el polígono
        prov_candidates = re.findall(
            r"(?:en|,)\s+(?!el\s+pol|pol[ií]gono)([A-Za-zÀ-ÿ]{3,}(?:\s+[A-Za-zÀ-ÿ]{3,})?)",
            text, re.IGNORECASE,
        )
        province = ""
        for cand in prov_candidates:
            cand_clean = cand.strip().title()
            if cand_clean.lower() != industrial_zone.lower() and len(cand_clean) > 2:
                province = cand_clean
                break
    else:
        # 1. Palabras después de preposiciones de lugar
        prep_hits = re.findall(
            r'\b(?:en|cerca de|en la ciudad de|ciudad de|municipio de|en el municipio de)\s+'
            r'([a-zà-ü][a-zÀ-ü]*(?:\s+[a-zÀ-ü]+)?)',
            text, re.IGNORECASE,
        )
        # 2. Palabras capitalizadas en el texto original
        cap_hits = re.findall(r'\b([A-ZÀ-Ü][a-zà-ü]{2,})\b', text)

        seen: list[str] = []
        for raw in prep_hits + cap_hits:
            normalized = raw.strip().title()
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
        "must_have": must_have,
        "min_employees": min_employees,
        "max_employees": max_employees,
        "industrial_zone": industrial_zone,
        "radius_km": radius_km,
        "target_description": text[:120],
        "_fallback": True,
    }


@router.get("/prospecting/skill-source")
async def get_skill_source() -> dict:
    """Devuelve el código real del bucle que ejecuta la búsqueda de negocios (_execute_run)."""
    source = inspect.getsource(ProspectingAgentService._execute_run)
    return {
        "qualname": "ProspectingAgentService._execute_run",
        "file": inspect.getsourcefile(ProspectingAgentService._execute_run),
        "source": source,
    }


def _verticals_context_block(prospecting: ProspectingAgentService) -> str:
    """Bloque de contexto con las verticales ACTIVAS configuradas en BBDD — nunca
    una lista fija en el prompt. sales_verticals es la unica fuente de verdad
    para clasificar (antes se consultaba el CRM en vivo; ahora el CRM se
    alimenta de aqui, no al reves).
    """
    active = prospecting.verticals.list_active()
    if not active:
        return "VERTICALES DISPONIBLES: ninguna configurada. Usa 'custom'."
    lines = "\n".join(
        f"- {v.slug} ({v.nombre})" + (f" — alias: {', '.join(v.aliases)}" if v.aliases else "")
        for v in active
    )
    return (
        "VERTICALES DISPONIBLES (elige EXACTAMENTE uno de estos slugs si alguno encaja "
        "semanticamente, aunque el usuario lo redacte distinto — NUNCA inventes un slug nuevo; "
        "usa 'custom' solo si de verdad no encaja ninguno):\n" + lines
    )


@router.post("/prospecting/interpret")
async def interpret_brief(
    payload: InterpretRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    """Interpreta texto libre y devuelve parámetros de prospección."""
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    llm = get_router()
    verticals_block = _verticals_context_block(prospecting)
    response = None
    try:
        response = await asyncio.wait_for(
            llm.call(
                messages=[
                    {"role": "system", "content": resolve_prompt_sync("sales.prospecting.interpret") + "\n\n" + verticals_block},
                    {"role": "user", "content": payload.text.strip()},
                ],
                tools=_INTERPRET_BRIEF_TOOL,
                tool_choice={"type": "function", "function": {"name": "set_prospecting_brief"}},
                # L1 tenia un modelo gratuito retirado por OpenRouter (404 siempre) — esto
                # hacia que TODA interpretacion cayera al fallback heuristico en silencio.
                # L2 es el mismo nivel "reasoning" que ya usa PEPO, con el mismo margen.
                preferred_level=2,
                temperature=0.1,
                max_tokens=900,
                timeout=14.0,
            ),
            timeout=18.0,            # cap global — fallback heurístico si todos los niveles son lentos
        )
    except asyncio.TimeoutError:
        logger.warning("interpret | llm.call timeout global (18s) — usando fallback heurístico")

    brief = None

    if response is not None and not response.error and response.tool_calls:
        try:
            brief = json.loads(response.tool_calls[0]["function"]["arguments"] or "{}")
        except (KeyError, TypeError, json.JSONDecodeError):
            brief = None

    # Fallback por reglas si el LLM falla, no llama a la tool, o devuelve basura.
    if brief is None:
        brief = _fallback_parse(payload.text, prospecting.verticals)
    # Puerta unica: aunque el LLM SI haya respondido, su slug se resuelve contra
    # BBDD igualmente — asi nunca puede colar un vertical inventado que no
    # exista en sales_verticals (resolve() respeta el slug tal cual si ya es
    # exacto, asi que esto no cambia nada cuando el LLM elige bien).
    brief["vertical"] = prospecting.verticals.resolve(brief.get("vertical", ""), fallback_text=payload.text).slug
    brief["vertical_created"] = False
    # Mapear campos del LLM (location/quantity) a los que espera _normalize_brief
    if "location" in brief and not brief.get("city"):
        brief["city"] = brief.pop("location")
    if "quantity" in brief and not brief.get("desired_count"):
        brief["desired_count"] = brief.pop("quantity")
    brief.setdefault("desired_count", 20)
    brief.setdefault("minimum_score", 40)
    brief.setdefault("represented_by", "assets")
    brief.setdefault("dry_run", True)
    brief.setdefault("must_have", [])
    try:
        orchestrated = await asyncio.wait_for(
            prospecting.orchestrate_brief(brief, original_text=payload.text.strip()),
            timeout=4.0,
        )
    except asyncio.TimeoutError:
        logger.warning("interpret | orchestrate_brief timeout (4s) — devolviendo brief base")
        orchestrated = {"brief": brief, "orchestration": {"refinement_applied": False, "refinement_notes": "timeout", "source_plan": {}, "autonomous_agents": [], "preserved_fields": []}}
    except Exception as exc:
        logger.error("interpret | orchestrate_brief error — {}", exc)
        orchestrated = {"brief": brief, "orchestration": {"refinement_applied": False, "refinement_notes": str(exc)[:100], "source_plan": {}, "autonomous_agents": [], "preserved_fields": []}}
    return {
        "status": "ok",
        "brief": orchestrated["brief"],
        "orchestration": orchestrated["orchestration"],
    }



_PROSPECTING_CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_geography",
            "description": (
                "Resuelve un topónimo real (ciudad, pueblo, pedanía) a su provincia y comunidad "
                "autónoma reales usando datos geográficos, no memoria. Úsalo SIEMPRE que el usuario "
                "mencione un lugar del que no estés 100% seguro de su provincia — especialmente "
                "pueblos pequeños o pedanías. No inventes la provincia sin comprobarla."
            ),
            "parameters": {
                "type": "object",
                "properties": {"place": {"type": "string"}},
                "required": ["place"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Pregunta al usuario UN dato imprescindible que de verdad falta (normalmente solo la ciudad).",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_brief",
            "description": "Entrega el brief final de prospección, con la geografía ya resuelta (llama a lookup_geography antes si hacía falta).",
            "parameters": {
                "type": "object",
                "properties": {
                    "reply": {"type": "string", "description": "Resumen breve y natural de lo que se va a buscar."},
                    "vertical": {"type": "string"},
                    "city": {"type": "string"},
                    "province": {"type": "string"},
                    "region": {"type": "string"},
                    "target_description": {"type": "string"},
                    "radius_km": {
                        "type": "integer",
                        "description": (
                            "SOLO si el usuario menciona explicitamente un radio o distancia "
                            "('en un radio de 20km', 'a menos de 15km de X'). Numero en kilometros, "
                            "entre 1 y 250. Si no lo menciona, omite este campo."
                        ),
                    },
                    "desired_count": {"type": "integer"},
                    "minimum_score": {"type": "integer"},
                    "represented_by": {"type": "string", "enum": ["assets", "automato", "other"]},
                    "must_have": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["reply", "vertical", "city"],
            },
        },
    },
]

_PROSPECTING_CHAT_MAX_STEPS = 4


async def _run_prospecting_chat_loop(history: list[dict], prospecting: ProspectingAgentService) -> dict | None:
    """Bucle con tool calling: resuelve geografia real antes de dar el brief por bueno.

    Mismo mecanismo que el bucle generico de PEPO (system_task_agent) — el LLM
    decide que herramienta llamar, lookup_geography se ejecuta sin confirmacion
    (lectura, sin efectos), y el bucle continua hasta ask_user o finish_brief.
    """
    llm = get_router()
    verticals_block = _verticals_context_block(prospecting)
    messages = [
        {"role": "system", "content": resolve_prompt_sync("sales.prospecting.chat") + "\n\n" + verticals_block},
        *history,
    ]

    for _ in range(_PROSPECTING_CHAT_MAX_STEPS):
        try:
            response = await asyncio.wait_for(
                llm.call(
                    messages=messages,
                    tools=_PROSPECTING_CHAT_TOOLS,
                    tool_choice="auto",
                    preferred_level=1,
                    temperature=0.2,
                    max_tokens=700,
                    timeout=8.0,
                ),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning("prospecting/chat | llm timeout")
            return None

        if response.error:
            return None

        if not response.tool_calls:
            return None

        call = response.tool_calls[0]
        fn = call.get("function", {})
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}

        # El modelo a veces pide varias herramientas a la vez en un mismo turno.
        # Solo actuamos sobre la primera, pero la API exige una respuesta "tool"
        # por CADA tool_call_id del turno — si falta alguna, el siguiente request
        # devuelve 400 (mensajes invalidos). Se registran las demas como ignoradas.
        messages.append({"role": "assistant", "content": response.content or None, "tool_calls": response.tool_calls})
        for extra_call in response.tool_calls[1:]:
            messages.append({
                "role": "tool", "tool_call_id": extra_call.get("id", ""),
                "content": "Ignorada — ya se proceso otra herramienta en este turno.",
            })

        if name == "lookup_geography":
            from nexus.utils.geocoding import geocode_place

            place_queried = args.get("place", "")
            geo = await geocode_place(place_queried)
            if not geo:
                # No confiamos en que el modelo redacte bien la pregunta de fallo — el
                # nombre exacto que fallo ya lo tenemos en codigo, lo devolvemos
                # deterministicamente en vez de esperar a que el LLM lo mencione.
                return {
                    "status": "clarifying",
                    "reply": f"No encuentro '{place_queried}' en el mapa — ¿lo has escrito bien? Dime la ciudad o pueblo exacto.",
                    "brief": None,
                }
            result_text = f"provincia={geo['province']}, region={geo['region']}, ciudad={geo['city']}"
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
            continue

        if name == "ask_user":
            return {"status": "clarifying", "reply": args.get("question", "¿Puedes darme mas detalles?"), "brief": None}

        if name == "finish_brief":
            brief = {k: v for k, v in args.items() if k != "reply"}
            return {"status": "ready", "reply": args.get("reply", ""), "brief": brief}

        return None

    return None


@router.post("/prospecting/chat")
async def prospecting_chat(
    payload: ProspectingChatRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    """Motor conversacional: extrae intención, resuelve geografía real y valida empíricamente antes de confirmar."""
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    history.append({"role": "user", "content": payload.message})

    parsed = await _run_prospecting_chat_loop(history, prospecting)

    if not parsed:
        # Fallback heurístico — combina todos los mensajes del usuario e intenta extraer parámetros
        all_user_text = " ".join(
            m["content"] for m in history if m["role"] == "user"
        )
        fb = _fallback_parse(all_user_text, prospecting.verticals)
        if fb.get("city"):
            # Sanear artefactos del parser heurístico
            fb["province"] = fb["city"]
            fb.pop("min_employees", None)
            fb.pop("max_employees", None)
            fb.pop("industrial_zone", None)
            # desired_count: re-buscar número en el texto combinado
            num_match = re.search(r"\b(\d+)\b", all_user_text)
            if num_match:
                candidate = int(num_match.group(1))
                if 1 <= candidate <= 200:
                    fb["desired_count"] = candidate
            parsed = {
                "status": "ready",
                "reply": f"(sin LLM) Buscaré {fb.get('vertical', '')} en {fb['city']}.",
                "brief": fb,
            }
        else:
            return {
                "status": "clarifying",
                "reply": "¿En qué ciudad quieres buscar y qué tipo de negocio?",
                "brief": None,
            }

    status = parsed.get("status", "clarifying")
    reply = str(parsed.get("reply", ""))
    brief = parsed.get("brief")

    # Probe empírico — solo advierte, nunca bloquea (DDG filtra directorios
    # y en ciudades grandes casi todo son directorios, dando falsos "empty")
    if status == "ready" and brief and brief.get("city"):
        probe = await prospecting.quick_probe(
            city=brief["city"],
            vertical=brief.get("vertical", ""),
        )
        if probe.get("quality") in ("empty", "sparse"):
            reply += " ⚠ La búsqueda de prueba encontró pocos resultados directos — puede que la zona tenga poca presencia online o que el run sea corto."

    if status == "ready" and brief:
        brief.setdefault("province", brief.get("city", ""))
        brief.setdefault("region", "")
        brief.setdefault("target_description", "")
        brief.setdefault("desired_count", 20)
        brief.setdefault("minimum_score", 40)
        brief.setdefault("represented_by", "assets")
        brief.setdefault("must_have", [])
        brief.setdefault("dry_run", True)

    from utils.logger import hito
    if status == "ready" and brief:
        hito(
            "sales.chat | pregunta=\"{pregunta}\" | ready | {vertical} en {city}, {province}",
            pregunta=payload.message[:120], vertical=brief.get("vertical"), city=brief.get("city"), province=brief.get("province"),
        )
    else:
        hito("sales.chat | pregunta=\"{pregunta}\" | clarifying | \"{reply}\"", pregunta=payload.message[:120], reply=reply[:120])

    return {"status": status, "reply": reply, "brief": brief}


@router.post("/prospecting/run", response_model=ProspectingRunResponse)
async def run_prospecting(
    payload: ProspectingRunRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingRunResponse:
    return await prospecting.run(payload)


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
    lead_stage: str | None = Query(default=None),
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> ProspectingResultListResponse:
    return await prospecting.list_results(
        run_id=run_id, min_score=min_score, crm_state=crm_state, vertical=vertical, lead_stage=lead_stage
    )


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


# ── Search Decomposer (Fase 1 del pipeline agéntico) ─────────────────────────

class DecomposeRequest(BaseModel):
    text: str
    requested_by: str = "anonymous"


@router.post("/prospecting/decompose")
async def decompose_search(payload: DecomposeRequest) -> dict:
    """Descompone una petición en lenguaje natural en un search intent estructurado.

    Nuevo endpoint standalone — no toca el pipeline existente.
    Fase 1 del pipeline agéntico de búsqueda.
    """
    from agents.search_decomposer_agent import SearchDecomposerAgent

    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    agent = SearchDecomposerAgent()
    result = await agent.decompose(payload.text, requested_by=payload.requested_by)
    return {"status": "ok", **result}


# ── Verticales comerciales (CRUD) ─────────────────────────────────────────────
# Fuente de verdad para clasificacion/scoring/discovery — ver
# nexus/prospecting/sales_verticals.py. Efecto inmediato: no hay cache, cada
# lectura va a BBDD, asi que una vertical creada aqui esta disponible en la
# siguiente peticion sin reiniciar Nexus.


class SalesVerticalBody(BaseModel):
    slug: str = ""
    nombre: str
    aliases: list[str] = []
    scoring_rules: dict = {}
    discovery_config: dict = {}
    crm_tags: list[str] = []
    crm_sector: str = "otros"
    activo: bool = True


class SalesVerticalUpdateBody(BaseModel):
    nombre: str | None = None
    aliases: list[str] | None = None
    scoring_rules: dict | None = None
    discovery_config: dict | None = None
    crm_tags: list[str] | None = None
    crm_sector: str | None = None


@router.get("/prospecting/verticals")
async def list_sales_verticals(
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    return {"verticals": [v.to_dict() for v in prospecting.verticals.list_all()]}


@router.post("/prospecting/verticals")
async def create_sales_vertical(
    payload: SalesVerticalBody,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    try:
        vertical = prospecting.verticals.create(
            slug=payload.slug or payload.nombre,
            nombre=payload.nombre,
            aliases=payload.aliases,
            scoring_rules=payload.scoring_rules,
            discovery_config=payload.discovery_config,
            crm_tags=payload.crm_tags,
            crm_sector=payload.crm_sector,
            activo=payload.activo,
        )
    except DuplicateVerticalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return vertical.to_dict()


@router.put("/prospecting/verticals/{slug}")
async def update_sales_vertical(
    slug: str,
    payload: SalesVerticalUpdateBody,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    try:
        vertical = prospecting.verticals.update(
            slug,
            nombre=payload.nombre,
            aliases=payload.aliases,
            scoring_rules=payload.scoring_rules,
            discovery_config=payload.discovery_config,
            crm_tags=payload.crm_tags,
            crm_sector=payload.crm_sector,
        )
    except VerticalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateVerticalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return vertical.to_dict()


class SalesVerticalActiveBody(BaseModel):
    activo: bool


@router.put("/prospecting/verticals/{slug}/activo")
async def set_sales_vertical_active(
    slug: str,
    payload: SalesVerticalActiveBody,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    try:
        vertical = prospecting.verticals.set_active(slug, payload.activo)
    except VerticalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProtectedVerticalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return vertical.to_dict()


@router.delete("/prospecting/verticals/{slug}")
async def delete_sales_vertical(
    slug: str,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
) -> dict:
    try:
        prospecting.verticals.delete(slug)
    except VerticalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProtectedVerticalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "slug": slug}
