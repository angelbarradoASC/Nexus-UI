"""tests/unit/test_prospecting_orchestrator_verify.py

Tests unitarios para ProspectingPromptOrchestrator.verify_brief — la
verificacion de ida y vuelta (via LLM local) que comprueba si el brief
estructurado representa fielmente el texto original del usuario.
"""

from __future__ import annotations

import pytest

from nexus.prospecting.models import ProspectingBrief
from nexus.prospecting.orchestrator import ProspectingPromptOrchestrator


class _FakeLLM:
    def __init__(self, *, enabled: bool = True, response: dict | None = None) -> None:
        self.enabled = enabled
        self._response = response if response is not None else {}
        self.calls: list[dict] = []

    async def extract_json(self, *, system_prompt: str, user_prompt: str, schema_hint: dict):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return dict(self._response)


def _brief(**overrides) -> ProspectingBrief:
    base = dict(vertical="asesoria", target_description="asesorias fiscales", city="Toledo")
    base.update(overrides)
    return ProspectingBrief(**base)


def _orchestrator(llm) -> ProspectingPromptOrchestrator:
    return ProspectingPromptOrchestrator(llm_client=llm, brave_enabled=False, places_enabled=True, ddg_enabled=True)


# ── Casos donde no hay nada que verificar ───────────────────────────────────

@pytest.mark.asyncio
async def test_no_original_text_returns_consistent_by_default():
    orchestrator = _orchestrator(_FakeLLM())

    result = await orchestrator.verify_brief(_brief(), original_text="")

    assert result == {"consistent": True, "issues": [], "missing_info": [], "confidence": 1.0}


@pytest.mark.asyncio
async def test_llm_disabled_returns_consistent_by_default():
    orchestrator = _orchestrator(_FakeLLM(enabled=False))

    result = await orchestrator.verify_brief(_brief(), original_text="busca asesorias en Toledo")

    assert result["consistent"] is True


@pytest.mark.asyncio
async def test_llm_no_response_marks_zero_confidence_but_not_inconsistent():
    """Si el LLM local no responde (timeout, modelo caido...), no se puede
    verificar — pero eso no significa que el brief este mal. Se marca con
    confianza 0 para que quede visible, no se oculta ni se penaliza el brief."""
    orchestrator = _orchestrator(_FakeLLM(response={}))

    result = await orchestrator.verify_brief(_brief(), original_text="busca asesorias en Toledo")

    assert result["consistent"] is True
    assert result["confidence"] == 0.0


# ── Casos con veredicto real del LLM ────────────────────────────────────────

@pytest.mark.asyncio
async def test_consistent_brief_passes_through():
    llm = _FakeLLM(response={"consistent": True, "issues": [], "missing_info": [], "confidence": 0.9})
    orchestrator = _orchestrator(llm)

    result = await orchestrator.verify_brief(_brief(), original_text="busca asesorias fiscales en Toledo")

    assert result["consistent"] is True
    assert result["confidence"] == 0.9
    assert len(llm.calls) == 1
    assert "busca asesorias fiscales en Toledo" in llm.calls[0]["user_prompt"]


@pytest.mark.asyncio
async def test_inconsistent_brief_surfaces_issues():
    llm = _FakeLLM(response={
        "consistent": False,
        "issues": ["El usuario pidio restaurantes, el brief dice asesorias"],
        "missing_info": [],
        "confidence": 0.85,
    })
    orchestrator = _orchestrator(llm)

    result = await orchestrator.verify_brief(_brief(), original_text="busca restaurantes en Toledo")

    assert result["consistent"] is False
    assert result["issues"] == ["El usuario pidio restaurantes, el brief dice asesorias"]


@pytest.mark.asyncio
async def test_confidence_is_clamped_to_0_1_range():
    llm = _FakeLLM(response={"consistent": True, "issues": [], "missing_info": [], "confidence": 5.0})
    orchestrator = _orchestrator(llm)

    result = await orchestrator.verify_brief(_brief(), original_text="busca asesorias en Toledo")

    assert result["confidence"] == 1.0


@pytest.mark.asyncio
async def test_malformed_confidence_falls_back_to_midpoint():
    llm = _FakeLLM(response={"consistent": True, "issues": [], "missing_info": [], "confidence": "no-numero"})
    orchestrator = _orchestrator(llm)

    result = await orchestrator.verify_brief(_brief(), original_text="busca asesorias en Toledo")

    assert result["confidence"] == 0.5


@pytest.mark.asyncio
async def test_issues_and_missing_info_are_deduplicated():
    llm = _FakeLLM(response={
        "consistent": False,
        "issues": ["falta ciudad", "falta ciudad", "Falta Ciudad"],
        "missing_info": [],
        "confidence": 0.7,
    })
    orchestrator = _orchestrator(llm)

    result = await orchestrator.verify_brief(_brief(), original_text="busca asesorias")

    assert result["issues"] == ["falta ciudad"]


# ── Integración con orchestrate() — el trace y el resultado final ──────────

@pytest.mark.asyncio
async def test_orchestrate_includes_verification_in_result():
    llm = _FakeLLM(response={"consistent": True, "issues": [], "missing_info": [], "confidence": 0.95})
    orchestrator = _orchestrator(llm)

    result = await orchestrator.orchestrate(_brief(), original_text="busca asesorias fiscales en Toledo")

    assert result["orchestration"]["verification"]["consistent"] is True
    assert result["orchestration"]["verification"]["confidence"] == 0.95


@pytest.mark.asyncio
async def test_orchestrate_records_brief_verifier_agent_trace():
    llm = _FakeLLM(response={
        "consistent": False,
        "issues": ["no coincide la geografia"],
        "missing_info": [],
        "confidence": 0.6,
    })
    orchestrator = _orchestrator(llm)

    result = await orchestrator.orchestrate(_brief(), original_text="busca asesorias en Madrid")

    agents = {a["agent_id"]: a for a in result["orchestration"]["autonomous_agents"]["agents"]}
    assert "brief_verifier" in agents
    assert agents["brief_verifier"]["status"] == "completed"
    assert agents["brief_verifier"]["warnings"] == ["no coincide la geografia"]
