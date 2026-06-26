"""Monthly API call budget tracker for Google Places.

Persists a counter per calendar month in a JSON file alongside
the prospecting data. Thread-safe via asyncio lock.

Usage in service:
    budget.check_or_raise()          # raises BudgetExceededError if hard limit hit
    calls = await places.search(...)  # returns (results, n_calls)
    await budget.increment(n_calls)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


SOFT_LIMIT = 1_000   # warn in UI
HARD_LIMIT = 1_400   # block the run


class BudgetExceededError(RuntimeError):
    """Raised when the monthly hard limit is about to be exceeded."""

    def __init__(self, current: int, limit: int) -> None:
        self.current = current
        self.limit = limit
        super().__init__(
            f"Límite mensual de llamadas a Google Places alcanzado: "
            f"{current}/{limit}. Prospección bloqueada hasta el mes siguiente."
        )


class PlacesApiBudget:
    """Persistent monthly counter for Google Places API calls."""

    def __init__(self, data_dir: Path | str) -> None:
        self._path = Path(data_dir) / "places_api_budget.json"
        self._lock = asyncio.Lock()

    # ── public ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Synchronous snapshot — safe to call from route handlers."""
        data = self._load()
        month = self._current_month()
        calls = data.get(month, 0)
        if calls >= HARD_LIMIT:
            state = "blocked"
        elif calls >= SOFT_LIMIT:
            state = "warning"
        else:
            state = "ok"
        return {
            "month": month,
            "calls": calls,
            "soft_limit": SOFT_LIMIT,
            "hard_limit": HARD_LIMIT,
            "remaining": max(0, HARD_LIMIT - calls),
            "status": state,
        }

    def check_or_raise(self) -> None:
        """Raise BudgetExceededError if the hard limit is already reached."""
        data = self._load()
        month = self._current_month()
        calls = data.get(month, 0)
        if calls >= HARD_LIMIT:
            raise BudgetExceededError(calls, HARD_LIMIT)

    async def increment(self, n: int) -> int:
        """Increment this month's counter by n. Returns new total."""
        async with self._lock:
            data = self._load()
            month = self._current_month()
            data[month] = data.get(month, 0) + n
            self._save(data)
            return data[month]

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _current_month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
