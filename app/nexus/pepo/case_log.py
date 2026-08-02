"""Log propio por caso de PEPO.

Deliberadamente independiente del AuditEntry/audit_repository general
del coordinador de Nexus: cada actuacion de PEPO acumula su propio log
mientras esta abierta, y se exporta como texto cuando el caso se
resuelve. Assets no permite adjuntar ficheros a un ticket hoy, asi que
el log exportado entra en la descripcion del ticket, no como adjunto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class CaseLogEntry:
    """Un evento dentro del log de un caso de PEPO."""

    case_id: str
    kind: str
    """"mensaje_usuario" | "mensaje_pepo" | "accion_maquina" | "decision" """
    actor: str
    """Quien origina el evento: "usuario" | "pepo" | "tecnico" """
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_line(self) -> str:
        return f"[{self.timestamp}] ({self.actor}) {self.kind}: {self.summary}"


class CaseLogStore:
    """Guarda el log de cada caso de PEPO por separado, indexado por case_id.

    No comparte almacen con el audit_repository general de NexusCoordinator
    — cada actuacion es exportable de forma independiente y autocontenida.
    En memoria por ahora: vive mientras el caso esta abierto en esta sesion
    de Desktop, y se vacia una vez exportado al ticket.
    """

    def __init__(self) -> None:
        self._logs: dict[str, list[CaseLogEntry]] = {}

    def append(self, entry: CaseLogEntry) -> None:
        self._logs.setdefault(entry.case_id, []).append(entry)

    def log(self, case_id: str, *, kind: str, actor: str, summary: str, details: dict[str, Any] | None = None) -> CaseLogEntry:
        entry = CaseLogEntry(case_id=case_id, kind=kind, actor=actor, summary=summary, details=details or {})
        self.append(entry)
        return entry

    def get(self, case_id: str) -> list[CaseLogEntry]:
        return list(self._logs.get(case_id, []))

    def export_as_text(self, case_id: str) -> str:
        entries = self.get(case_id)
        if not entries:
            return f"Sin actividad registrada para el caso {case_id}."
        header = f"=== Log de PEPO -- caso {case_id} ({len(entries)} eventos) ==="
        lines = [entry.to_line() for entry in entries]
        return "\n".join([header, *lines])

    def clear(self, case_id: str) -> None:
        self._logs.pop(case_id, None)
