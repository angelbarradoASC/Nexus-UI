"""
app/nexus/connectors/base.py
------------------------------
Interfaz IConnection — contrato que deben cumplir todos los conectores.

El AgentExecutionContext habla con IConnection.run().
No sabe si hay SSH, WinRM, REST API o SNMP debajo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CommandResult:
    stdout:    str
    stderr:    str
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """stdout si hay salida, stderr si no."""
        return self.stdout.strip() or self.stderr.strip()

    def __str__(self) -> str:
        out = self.stdout.strip()
        err = self.stderr.strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr] {err}")
        return "\n".join(parts) or f"(exit {self.exit_code})"


class IConnection(ABC):
    """Contrato de conexión a un dispositivo gestionado."""

    @abstractmethod
    async def run(self, command: str, timeout: int = 30) -> CommandResult: ...

    @abstractmethod
    async def close(self) -> None: ...

    async def __aenter__(self) -> "IConnection":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
