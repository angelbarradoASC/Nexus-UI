"""
desktop/local_agents/mouse_agent.py
-------------------------------------
MouseAgent — ajusta la velocidad del puntero del raton en Windows.

Piloto de la capacidad "desktop.system_setting": PEPO puede proponer un
cambio real sobre la maquina local, pero solo lo aplica tras confirmacion
explicita del usuario en el mismo chat.

Nivel de permisos: OPERATE (escribe en la configuracion del sistema).
Lista blanca: solo velocidad de raton. Nada de comandos arbitrarios.
"""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("nexus.mouse_agent")

SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

MOUSE_SPEED_MIN = 1
MOUSE_SPEED_MAX = 20
MOUSE_SPEED_DEFAULT = 10
_STEP = 3


@dataclass(slots=True)
class PendingMouseChange:
    current_value: int
    target_value: int
    direction: str


class MouseAgent:
    """Lee y ajusta la velocidad del raton, con confirmacion en dos pasos."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingMouseChange] = {}

    def get_speed(self) -> int:
        """Devuelve la velocidad actual (1-20)."""
        value = ctypes.c_int()
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(value), 0)
        return int(value.value)

    def _set_speed(self, value: int) -> int:
        value = max(MOUSE_SPEED_MIN, min(MOUSE_SPEED_MAX, value))
        ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETMOUSESPEED, 0, value, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        )
        logger.info("Velocidad de raton aplicada | valor=%s", value)
        return value

    def propose_change(self, context_id: str, direction: str) -> dict[str, Any]:
        """Calcula el cambio propuesto y lo guarda pendiente de confirmar."""
        current = self.get_speed()
        if direction == "max":
            target = MOUSE_SPEED_MAX
        elif direction == "min":
            target = MOUSE_SPEED_MIN
        elif direction == "reset":
            target = MOUSE_SPEED_DEFAULT
        elif direction == "up":
            target = min(MOUSE_SPEED_MAX, current + _STEP)
        else:  # "down"
            target = max(MOUSE_SPEED_MIN, current - _STEP)

        self._pending[context_id] = PendingMouseChange(
            current_value=current, target_value=target, direction=direction
        )
        return {"current": current, "target": target, "direction": direction}

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    def list_pending(self) -> list[dict[str, Any]]:
        """Solo lectura, para el gestor de agentes — nunca expone nada sensible."""
        return [
            {
                "context_id": context_id,
                "agent_id": "mouse",
                "kind": "mouse_speed",
                "summary": f"Cambiar velocidad del raton: {pending.current_value} -> {pending.target_value} ({pending.direction})",
            }
            for context_id, pending in self._pending.items()
        ]

    def confirm(self, context_id: str) -> dict[str, Any] | None:
        """Aplica el cambio pendiente para este contexto, si existe."""
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return None
        applied = self._set_speed(pending.target_value)
        return {"previous": pending.current_value, "applied": applied}

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)
