"""Mini ticketing routes for the Operator panel."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nexus.api.dependencies.auth import get_operations_manager
from nexus.operations import AssetsOperationsService

router = APIRouter()


class AssetsTicketPayload(BaseModel):
    title: str = ""
    ticket_type: str = "task"
    status: str = "pending"
    priority: str = "medium"
    due_date: str = ""
    company_id: int | None = None
    project_id: int | None = None
    assigned_to_id: int | None = None
    source: str = "manual"
    description: str = ""


class AssetsTicketUpdatePayload(BaseModel):
    title: str | None = None
    ticket_type: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    company_id: int | None = None
    project_id: int | None = None
    assigned_to_id: int | None = None
    source: str | None = None
    description: str | None = None


class AssetsTicketFromMessagePayload(BaseModel):
    message: str
    source: str = "codex"
    actor: str = "operator"
    trigger_kind: str = "operator"
    context: dict[str, Any] = Field(default_factory=dict)


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    detail = str(exc) or exc.__class__.__name__
    return HTTPException(status_code=502, detail=detail)


@router.get("/assets-ops/status")
async def get_assets_ops_status(
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, Any]:
    try:
        return await operations.status()
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc


@router.get("/assets-ops/bootstrap")
async def get_assets_ops_bootstrap(
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, Any]:
    try:
        return await operations.bootstrap()
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc


@router.get("/assets-ops/tickets")
async def list_assets_ops_tickets(
    operations: AssetsOperationsService = Depends(get_operations_manager),
    limit: int = Query(default=12, ge=1, le=100),
) -> dict[str, Any]:
    try:
        payload = await operations.list_tickets()
        payload["tasks"] = list(payload.get("tasks", []))[:limit]
        payload["limit"] = limit
        return payload
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc


@router.post("/assets-ops/tickets")
async def create_assets_ops_ticket(
    payload: AssetsTicketPayload,
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, Any]:
    try:
        created = await operations.create_ticket(payload.model_dump())
        return {"status": "created", "result": created}
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc


@router.post("/assets-ops/tickets/from-message")
async def create_assets_ops_ticket_from_message(
    payload: AssetsTicketFromMessagePayload,
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, Any]:
    try:
        return await operations.create_ticket_from_message(
            payload.message,
            source=payload.source,
            actor=payload.actor,
            trigger_kind=payload.trigger_kind,
            context=payload.context,
        )
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc


@router.put("/assets-ops/tickets/{task_id}")
async def update_assets_ops_ticket(
    task_id: int,
    payload: AssetsTicketUpdatePayload,
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, Any]:
    try:
        updated = await operations.update_ticket(task_id, payload.model_dump(exclude_unset=True))
        return {"status": "updated", "result": updated}
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc


@router.delete("/assets-ops/tickets/{task_id}")
async def delete_assets_ops_ticket(
    task_id: int,
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, Any]:
    try:
        deleted = await operations.delete_ticket(task_id)
        return {"status": "deleted", "result": deleted}
    except Exception as exc:  # pragma: no cover - remote failure variance
        raise _to_http_error(exc) from exc
