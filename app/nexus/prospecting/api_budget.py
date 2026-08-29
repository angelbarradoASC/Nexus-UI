"""Monthly API call budget tracker — control férreo sobre APIs de pago/con
cuota (Google Places, Brave Search...).

Persiste un contador por mes natural en un JSON junto a los datos de
prospección. Seguro frente a condiciones de carrera via asyncio lock. Un
`_MonthlyApiBudget` generico por proveedor — antes solo existia para
Google Places; Brave hacia llamadas (una por query de discovery, una por
candidato en enriquecimiento) sin ningun tope real, solo un throttle de
peticiones/segundo que no limita el volumen mensual.

Usage in service:
    budget.check_or_raise()           # raises BudgetExceededError if hard limit hit
    calls = await client.search(...)  # returns (results, n_calls) o similar
    await budget.increment(n_calls)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

# Google Places — sin cambios respecto al comportamiento anterior.
SOFT_LIMIT = 1_000   # warn in UI
HARD_LIMIT = 1_400   # block the run

# Brave Search — desde 2026 ya no da un nivel gratis universal (verificado
# en vivo: cuentas nuevas solo tienen $5/mes en creditos, ~1000 queries).
# Limites conservadores por defecto, pensados para no agotar el credito
# mensual antes de que el usuario se de cuenta — configurables desde
# /nexus/settings, no un valor fijo sin mando.
BRAVE_SOFT_LIMIT = 800
BRAVE_HARD_LIMIT = 1_000


class BudgetExceededError(RuntimeError):
    """Raised when the monthly hard limit is about to be exceeded."""

    def __init__(self, current: int, limit: int, *, label: str = "Google Places") -> None:
        self.current = current
        self.limit = limit
        self.label = label
        super().__init__(
            f"Límite mensual de llamadas a {label} alcanzado: "
            f"{current}/{limit}. Prospección bloqueada hasta el mes siguiente."
        )


class _MonthlyApiBudget:
    """Contador mensual persistente generico — cada proveedor (Places,
    Brave...) tiene su propio fichero, limites y etiqueta de error."""

    def __init__(self, data_dir: Path | str, *, filename: str, soft_limit: int, hard_limit: int, label: str) -> None:
        self._path = Path(data_dir) / filename
        self._lock = asyncio.Lock()
        self._soft_limit = soft_limit
        self._hard_limit = hard_limit
        self._label = label

    # ── public ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Synchronous snapshot — safe to call from route handlers."""
        data = self._load()
        month = self._current_month()
        calls = data.get(month, 0)
        if calls >= self._hard_limit:
            state = "blocked"
        elif calls >= self._soft_limit:
            state = "warning"
        else:
            state = "ok"
        return {
            "provider": self._label,
            "month": month,
            "calls": calls,
            "soft_limit": self._soft_limit,
            "hard_limit": self._hard_limit,
            "remaining": max(0, self._hard_limit - calls),
            "status": state,
        }

    def check_or_raise(self) -> None:
        """Raise BudgetExceededError if the hard limit is already reached."""
        data = self._load()
        month = self._current_month()
        calls = data.get(month, 0)
        if calls >= self._hard_limit:
            raise BudgetExceededError(calls, self._hard_limit, label=self._label)

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


class PlacesApiBudget(_MonthlyApiBudget):
    """Persistent monthly counter for Google Places API calls."""

    def __init__(self, data_dir: Path | str) -> None:
        super().__init__(data_dir, filename="places_api_budget.json", soft_limit=SOFT_LIMIT, hard_limit=HARD_LIMIT, label="Google Places")


class BraveApiBudget(_MonthlyApiBudget):
    """Persistent monthly counter for Brave Search API calls — cubre tanto
    el discovery (una llamada por query) como el enriquecimiento (una
    llamada por candidato), que antes no tenian ningun tope de volumen."""

    def __init__(self, data_dir: Path | str, *, soft_limit: int | None = None, hard_limit: int | None = None) -> None:
        super().__init__(
            data_dir,
            filename="brave_api_budget.json",
            soft_limit=soft_limit if soft_limit is not None else BRAVE_SOFT_LIMIT,
            hard_limit=hard_limit if hard_limit is not None else BRAVE_HARD_LIMIT,
            label="Brave Search",
        )
