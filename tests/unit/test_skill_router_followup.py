"""tests/unit/test_skill_router_followup.py

Bug real visto en vivo: tras hablar de la velocidad del raton, la pregunta
"que switches y routers cisco la soportan?" se clasifico como
desktop.mouse_speed (PEPO contesto "Voy a ponerla en 3. ¿Confirmas?") porque
el clasificador LLM recibia SIEMPRE el historial y trataba cualquier mensaje
como un seguimiento del turno anterior. Ahora el historial solo se le pasa
cuando el mensaje es un seguimiento corto ("bajala a la mitad").
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.runtime.skill_router import DesktopSkillRouter

_HISTORY = [
    {"role": "user", "content": "la velocidad del raton va muy lenta"},
    {"role": "assistant", "content": "La velocidad actual del raton es 6. Voy a ponerla en 8. ¿Confirmas?"},
]


class _CapturingRouter:
    def __init__(self, skill_id: str = "general.respuesta") -> None:
        self.skill_id = skill_id
        self.calls: list[list[dict]] = []

    async def call(self, messages, **_kwargs):
        self.calls.append(messages)
        return SimpleNamespace(
            error=None,
            content=json.dumps({"skill_id": self.skill_id, "confidence": 0.9, "rationale": "t", "entities": {}}),
        )


@pytest.mark.parametrize("text", [
    "bajala a la mitad",
    "hazlo otra vez",
    "vuelve a hacerlo",
    "subela un poco mas",
    "esa misma",
    "dale",
])
def test_short_followups_are_detected(text):
    assert DesktopSkillRouter.is_followup(text) is True


@pytest.mark.parametrize("text", [
    "que switches y routers cisco la soportan?",
    "cuales son los trending topics en twitter hoy en españa",
    "no funciona el servidor web-prod-01",
    "cuanto vale el bitcoin",
    "tengo algun correo de hoy?",
    "",
])
def test_messages_with_their_own_topic_are_not_followups(text):
    assert DesktopSkillRouter.is_followup(text) is False


@pytest.mark.asyncio
async def test_history_is_not_sent_to_the_classifier_for_a_self_contained_question():
    llm = _CapturingRouter()

    await DesktopSkillRouter().resolve_llm("que switches y routers cisco la soportan?", llm, history=_HISTORY)

    sent = llm.calls[0]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert "raton" not in json.dumps(sent[1:], ensure_ascii=False)


@pytest.mark.asyncio
async def test_history_is_still_sent_for_a_short_followup():
    llm = _CapturingRouter(skill_id="desktop.mouse_speed")

    resolution = await DesktopSkillRouter().resolve_llm("bajala a la mitad", llm, history=_HISTORY)

    sent = llm.calls[0]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert resolution.to_dict()["skill_id"] == "desktop.mouse_speed"


def test_prompt_tells_the_classifier_to_use_history_only_for_references():
    from nexus.prompts import resolve_prompt_sync

    prompt = resolve_prompt_sync("pepo.skill_intention")

    assert "SOLO para resolver referencias" in prompt
