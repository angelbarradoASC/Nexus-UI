"""
app/nexus/api/routes/approvals.py
-----------------------------------
Endpoints del Human-in-the-Loop approval queue.

Flujo:
  1. Un agente ejecuta un plan con GuardrailEngine.
  2. Para acciones DESTRUCTIVE, no ejecuta — crea un PendingApproval.
  3. El operador consulta GET /approvals y decide aprobar o rechazar.
  4. El agente, en el próximo ciclo, consulta el estado y continúa.

Endpoints:
  GET  /approvals               — listar todas (con filtro de estado)
  GET  /approvals/pending/count — cuántas pendientes (para el badge de UI)
  GET  /approvals/{id}          — detalle de una aprobación
  POST /approvals/{id}/approve  — aprobar
  POST /approvals/{id}/reject   — rechazar
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_pending_approvals
from nexus.audit.pending_approvals import MemoryPendingApprovalRepository

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    resolved_by: str = "operator"


class RejectRequest(BaseModel):
    resolved_by: str = "operator"
    reason: str = ""


# ── Rutas ─────────────────────────────────────────────────────────────────────

@router.get("/approvals")
async def list_approvals(
    status: str | None = None,
    repo: MemoryPendingApprovalRepository = Depends(get_pending_approvals),
) -> dict[str, object]:
    """
    Lista aprobaciones con filtro opcional por estado:
    ?status=pending | approved | rejected | (omitir = todas)
    """
    if status == "pending":
        entries = await repo.list_pending()
    else:
        entries = await repo.list_all()
        if status in ("approved", "rejected"):
            entries = [e for e in entries if e.status == status]

    return {
        "total": len(entries),
        "pending": repo.pending_count,
        "approvals": [e.to_dict() for e in entries],
    }


@router.get("/approvals/pending/count")
async def pending_count(
    repo: MemoryPendingApprovalRepository = Depends(get_pending_approvals),
) -> dict[str, int]:
    """Badge endpoint: número de aprobaciones pendientes."""
    return {"pending": repo.pending_count}


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    repo: MemoryPendingApprovalRepository = Depends(get_pending_approvals),
) -> dict[str, object]:
    entry = await repo.get(approval_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Aprobación no encontrada")
    return entry.to_dict()


@router.post("/approvals/{approval_id}/approve")
async def approve_action(
    approval_id: str,
    body: ApproveRequest,
    repo: MemoryPendingApprovalRepository = Depends(get_pending_approvals),
) -> dict[str, object]:
    """
    Aprueba una acción destructiva.
    El agente responsable debe consultar el estado para continuar.
    """
    entry = await repo.approve(approval_id, resolved_by=body.resolved_by)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Aprobación no encontrada o ya fue resuelta",
        )
    return {
        "ok": True,
        "approval_id": entry.approval_id,
        "status": entry.status,
        "resolved_by": entry.resolved_by,
        "resolved_at": entry.resolved_at,
    }


@router.post("/approvals/{approval_id}/reject")
async def reject_action(
    approval_id: str,
    body: RejectRequest,
    repo: MemoryPendingApprovalRepository = Depends(get_pending_approvals),
) -> dict[str, object]:
    """Rechaza una acción destructiva y registra el motivo."""
    entry = await repo.reject(
        approval_id,
        resolved_by=body.resolved_by,
        reason=body.reason,
    )
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Aprobación no encontrada o ya fue resuelta",
        )
    return {
        "ok": True,
        "approval_id": entry.approval_id,
        "status": entry.status,
        "resolved_by": entry.resolved_by,
        "resolved_at": entry.resolved_at,
        "rejection_reason": entry.rejection_reason,
    }
