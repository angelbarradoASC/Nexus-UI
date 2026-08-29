"""tests/unit/test_api_budget.py

Tests unitarios para el control de presupuesto mensual de APIs de pago/con
cuota — PlacesApiBudget (sin cambios de comportamiento) y BraveApiBudget
(nuevo, mismo mecanismo generalizado via _MonthlyApiBudget).
"""

from __future__ import annotations

import pytest

from nexus.prospecting.api_budget import (
    BraveApiBudget,
    BudgetExceededError,
    PlacesApiBudget,
)


# ── PlacesApiBudget — comportamiento preexistente, no debe haber cambiado ───

def test_places_budget_starts_at_zero(tmp_path):
    budget = PlacesApiBudget(tmp_path)

    status = budget.status()

    assert status["calls"] == 0
    assert status["soft_limit"] == 1_000
    assert status["hard_limit"] == 1_400
    assert status["status"] == "ok"
    assert status["provider"] == "Google Places"


@pytest.mark.asyncio
async def test_places_budget_increments_and_persists(tmp_path):
    budget = PlacesApiBudget(tmp_path)

    total = await budget.increment(5)

    assert total == 5
    assert PlacesApiBudget(tmp_path).status()["calls"] == 5


@pytest.mark.asyncio
async def test_places_budget_check_or_raise_blocks_at_hard_limit(tmp_path):
    budget = PlacesApiBudget(tmp_path)
    await budget.increment(1_400)

    with pytest.raises(BudgetExceededError) as exc_info:
        budget.check_or_raise()

    assert exc_info.value.label == "Google Places"
    assert "Google Places" in str(exc_info.value)


def test_places_budget_warning_state_at_soft_limit(tmp_path):
    budget = PlacesApiBudget(tmp_path)

    import asyncio
    asyncio.run(budget.increment(1_000))

    assert budget.status()["status"] == "warning"


# ── BraveApiBudget — nuevo, mismo mecanismo ─────────────────────────────────

def test_brave_budget_uses_its_own_file_and_defaults(tmp_path):
    brave = BraveApiBudget(tmp_path)
    places = PlacesApiBudget(tmp_path)

    assert brave.status()["provider"] == "Brave Search"
    assert brave.status()["soft_limit"] == 800
    assert brave.status()["hard_limit"] == 1_000
    # No comparten contador — son ficheros distintos.
    assert brave.status()["calls"] == 0
    assert places.status()["calls"] == 0


@pytest.mark.asyncio
async def test_brave_and_places_budgets_are_independent(tmp_path):
    brave = BraveApiBudget(tmp_path)
    places = PlacesApiBudget(tmp_path)

    await brave.increment(10)

    assert brave.status()["calls"] == 10
    assert places.status()["calls"] == 0


@pytest.mark.asyncio
async def test_brave_budget_check_or_raise_blocks_at_hard_limit(tmp_path):
    brave = BraveApiBudget(tmp_path)
    await brave.increment(1_000)

    with pytest.raises(BudgetExceededError) as exc_info:
        brave.check_or_raise()

    assert exc_info.value.label == "Brave Search"
    assert "Brave Search" in str(exc_info.value)


def test_brave_budget_accepts_custom_limits(tmp_path):
    brave = BraveApiBudget(tmp_path, soft_limit=50, hard_limit=100)

    status = brave.status()

    assert status["soft_limit"] == 50
    assert status["hard_limit"] == 100


@pytest.mark.asyncio
async def test_brave_budget_custom_hard_limit_blocks_correctly(tmp_path):
    brave = BraveApiBudget(tmp_path, soft_limit=5, hard_limit=10)
    await brave.increment(10)

    with pytest.raises(BudgetExceededError):
        brave.check_or_raise()


def test_brave_budget_none_limits_fall_back_to_module_defaults(tmp_path):
    brave = BraveApiBudget(tmp_path, soft_limit=None, hard_limit=None)

    status = brave.status()

    assert status["soft_limit"] == 800
    assert status["hard_limit"] == 1_000
