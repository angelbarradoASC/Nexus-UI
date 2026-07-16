"""
app/nexus/audit/pending_approvals.py
--------------------------------------
Repositorio de acciones agenticas pausadas a la espera de aprobación humana.

Una acción llega aquí cuando GuardrailEngine.evaluate() devuelve
verdict="human_required". El operador puede aprobarla o rechazarla
desde la UI de NEXUS antes de que el agente la ejecute.

Diseño:
  - In-memory por defecto (idéntico al patrón de IncidentRepository)
  - No tiene dependencias de LLM ni de otros servicios
  - Genera approval_id únicos firmados con prefijo legible
  - Estados: pending → approved | rejected

En el futuro este repositorio puede respaldarse con Mongo usando el mismo
patrón que MongoAuditRepository (upgrade via use_persistence).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


# ── Modelo ────────────────────────────────────────────────────────────────────

@dataclass
class PendingApproval:
    approval_id:      str
    trace_id:         str
    agent:            str
    triggered_by:     str
    step:             int
    thought:          str
    action:           str
    risk_class:       str    # "destructive"
    risk_score:       float
    created_at:       str
    status:           str = "pending"       # pending | approved | rejected
    resolved_by:      str | None = None
    resolved_at:      str | None = None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Repositorio en memoria ────────────────────────────────────────────────────

class MemoryPendingApprovalRepository:
    """
    Almacena aprobaciones pendientes en memoria.
    Thread-safe a nivel de uso normal (asyncio single-threaded).
    """

    def __init__(self) -> None:
        self._store: dict[str, PendingApproval] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Escritura ─────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        trace_id:     str,
        agent:        str,
        triggered_by: str,
        step:         int,
        thought:      str,
        action:       str,
        risk_class:   str,
        risk_score:   float,
    ) -> PendingApproval:
        """Registra una nueva acción pendiente de aprobación."""
        approval_id = f"appr-{uuid.uuid4().hex[:10]}"
        entry = PendingApproval(
            approval_id=approval_id,
            trace_id=trace_id,
            agent=agent,
            triggered_by=triggered_by,
            step=step,
            thought=thought,
            action=action,
            risk_class=risk_class,
            risk_score=round(risk_score, 3),
            created_at=self._now(),
        )
        self._store[approval_id] = entry
        return entry

    async def approve(self, approval_id: str, resolved_by: str) -> PendingApproval | None:
        """Aprueba una acción pendiente. Devuelve None si no existe o ya fue resuelta."""
        entry = self._store.get(approval_id)
        if entry is None or entry.status != "pending":
            return None
        entry.status = "approved"
        entry.resolved_by = resolved_by
        entry.resolved_at = self._now()
        return entry

    async def reject(
        self,
        approval_id: str,
        resolved_by: str,
        reason: str = "",
    ) -> PendingApproval | None:
        """Rechaza una acción pendiente."""
        entry = self._store.get(approval_id)
        if entry is None or entry.status != "pending":
            return None
        entry.status = "rejected"
        entry.resolved_by = resolved_by
        entry.resolved_at = self._now()
        entry.rejection_reason = reason or "Rechazado por el operador"
        return entry

    # ── Consultas ─────────────────────────────────────────────────────────────

    async def get(self, approval_id: str) -> PendingApproval | None:
        return self._store.get(approval_id)

    async def list_pending(self) -> list[PendingApproval]:
        return [e for e in self._store.values() if e.status == "pending"]

    async def list_all(self, limit: int = 100) -> list[PendingApproval]:
        entries = sorted(self._store.values(), key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    async def list_by_trace(self, trace_id: str) -> list[PendingApproval]:
        return [e for e in self._store.values() if e.trace_id == trace_id]

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self._store.values() if e.status == "pending")
