"""Runbook registry for monitoring alerts."""

from __future__ import annotations

from typing import Any


DEFAULT_RUNBOOKS: dict[str, dict[str, Any]] = {
    "HighCPU": {
        "summary": "Comprobar carga, proceso dominante y margen antes de reiniciar nada.",
        "steps": [
            "consultar carga CPU en Prometheus",
            "identificar host afectado",
            "recomendar diagnostico SSH o escalar si se mantiene",
        ],
        "auto_actions": ["diagnose_only"],
    },
    "DiskFull": {
        "summary": "Verificar uso de disco y crecimiento anomalo.",
        "steps": [
            "consultar porcentaje de uso",
            "comprobar host afectado",
            "abrir incidente critico si supera umbral duro",
        ],
        "auto_actions": ["diagnose_only", "ticket"],
    },
}


class RunbookRegistry:
    """Resolves runbooks for alerts and incidents."""

    def __init__(self, runbooks: dict[str, dict[str, Any]] | None = None) -> None:
        self._runbooks = runbooks or DEFAULT_RUNBOOKS

    def get(self, alert_name: str) -> dict[str, Any]:
        return self._runbooks.get(
            alert_name,
            {
                "summary": "Sin runbook especifico; requiere triage manual.",
                "steps": ["revisar alerta", "recoger contexto", "decidir diagnostico o ticket"],
                "auto_actions": ["triage_only"],
            },
        )

    def list_all(self) -> list[dict[str, Any]]:
        return [
            {"alert_name": name, **definition}
            for name, definition in sorted(self._runbooks.items())
        ]
