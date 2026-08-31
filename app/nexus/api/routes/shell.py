"""Chat del Shell (pagina Open-Nexus) — habla directo con el LLM local en
192.168.68.150 en vez del router de Groq compartido (LLMRouter, usado por
PEPO y el resto del chat general), y con capacidad real de usar
herramientas: qwen3:8b en ese servidor ya tiene tool-calling activado en
Ollama (capabilities=['completion','tools','thinking']), Ollama aplica la
plantilla de tool-calling del propio modelo por su cuenta — nosotros solo
mandamos `tools` y leemos message.tool_calls.

Mismo principio que el bucle de SystemTaskAgent (PEPO): un toolbox fijo +
un bucle generico, el LLM decide cuando usar cada herramienta — nada de
codigo Python distinto por cada tipo de pregunta. Se empieza con
herramientas de solo lectura sobre lo que el propio Shell ya muestra en su
panel de monitorizacion (estado de servicios, alarmas); añadir mas
herramientas mas adelante es solo ampliar _SHELL_TOOLS + _run_tool.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_coordinator, get_prospecting_manager
from nexus.orchestration.coordinator import NexusCoordinator
from nexus.prospecting.service import ProspectingAgentService

router = APIRouter()

_SYSTEM_PROMPT = (
    "Eres un asistente breve y directo. Responde siempre en español. "
    "Si la pregunta es sobre el estado de los servicios o las alarmas recientes, "
    "usa las herramientas disponibles en vez de inventar datos."
)

_MAX_TOOL_STEPS = 4

_SHELL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_service_status",
            "description": "Consulta el estado actual de los servicios de monitorizacion (Prometheus, Alertmanager, Grafana).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_alarms",
            "description": "Lista las alarmas/incidentes mas recientes registrados en Nexus.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Cuantas alarmas devolver como maximo (por defecto 5)"},
                },
            },
        },
    },
]


async def _run_tool(name: str, args: dict, coordinator: NexusCoordinator) -> str:
    if name == "get_service_status":
        data = await coordinator.get_collector_status()
        lines = [f"- {c.get('name')}: {c.get('status')}" for c in data.get("collectors", [])]
        return f"Estado general: {data.get('overall')}\n" + "\n".join(lines)

    if name == "get_recent_alarms":
        try:
            limit = int(args.get("limit") or 5)
        except (TypeError, ValueError):
            limit = 5
        data = await coordinator.list_incidents(limit=limit)
        if not data.incidents:
            return "Sin alarmas recientes."
        lines = [
            f"- [{i.get('severity', '?')}] {i.get('title') or i.get('incident_id')} ({i.get('status', '?')})"
            for i in data.incidents[:limit]
        ]
        return "\n".join(lines)

    return f"Herramienta desconocida: {name}"


class ShellChatRequest(BaseModel):
    message: str


class ShellChatResponse(BaseModel):
    response: str
    model: str
    available: bool


@router.post("/shell/chat", response_model=ShellChatResponse)
async def shell_chat(
    payload: ShellChatRequest,
    prospecting: ProspectingAgentService = Depends(get_prospecting_manager),
    coordinator: NexusCoordinator = Depends(get_coordinator),
) -> ShellChatResponse:
    llm = prospecting.local_llm
    model = llm.descriptor.get("model", "")

    if not llm.enabled:
        return ShellChatResponse(
            response="El LLM local (192.168.68.150) no esta disponible ahora mismo — revisa LOCAL_LLM_ENABLED/LOCAL_LLM_BASE_URL.",
            model=model,
            available=False,
        )

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": payload.message},
    ]

    for _ in range(_MAX_TOOL_STEPS):
        result = await llm.chat_with_tools(messages=messages, tools=_SHELL_TOOLS)

        if result.error:
            return ShellChatResponse(
                response="El LLM local no ha respondido (revisa que el servicio en 192.168.68.150 este arriba).",
                model=model,
                available=False,
            )

        if not result.tool_calls:
            return ShellChatResponse(
                response=result.content or "El LLM local no ha respondido (revisa que el servicio en 192.168.68.150 este arriba).",
                model=model,
                available=bool(result.content),
            )

        messages.append({"role": "assistant", "content": result.content, "tool_calls": result.tool_calls})
        for call in result.tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args or {}
            tool_result = await _run_tool(name, args, coordinator)
            messages.append({"role": "tool", "content": tool_result})

    return ShellChatResponse(
        response="No he podido resolverlo con las herramientas disponibles.",
        model=model,
        available=True,
    )
