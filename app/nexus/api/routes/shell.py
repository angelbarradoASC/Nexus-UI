"""Chat del Shell (pagina Open-Nexus) — habla directo con el LLM local en
192.168.68.150 en vez del router de Groq compartido (LLMRouter, usado por
PEPO y el resto del chat general).

Pedido explicito del usuario: quiere que ESTE chat en concreto apunte al
LLM local. Reutiliza LOCAL_LLM_* (mismo LLM que ya usan Campaña/Prospeccion
para verificacion) via ProspectingAgentService.local_llm — expuesto para
exactamente este motivo, no se crea una segunda conexion.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_prospecting_manager
from nexus.prospecting.service import ProspectingAgentService

router = APIRouter()

_SYSTEM_PROMPT = "Eres un asistente breve y directo. Responde siempre en español."


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
) -> ShellChatResponse:
    llm = prospecting.local_llm
    model = llm.descriptor.get("model", "")

    if not llm.enabled:
        return ShellChatResponse(
            response="El LLM local (192.168.68.150) no esta disponible ahora mismo — revisa LOCAL_LLM_ENABLED/LOCAL_LLM_BASE_URL.",
            model=model,
            available=False,
        )

    text = await llm.complete(system_prompt=_SYSTEM_PROMPT, user_prompt=payload.message)
    return ShellChatResponse(
        response=text or "El LLM local no ha respondido (revisa que el servicio en 192.168.68.150 este arriba).",
        model=model,
        available=bool(text),
    )
