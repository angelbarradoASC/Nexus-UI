"""PEPO routes: log por caso."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from nexus.api.dependencies.auth import get_case_log_store, get_operations_manager
from nexus.operations import AssetsOperationsService
from nexus.pepo import CaseLogStore

router = APIRouter()


@router.get("/pepo/case/{case_id:path}/log")
def get_case_log(case_id: str, case_log: CaseLogStore = Depends(get_case_log_store)) -> dict[str, object]:
    """Return the raw log entries for a PEPO case."""
    entries = case_log.get(case_id)
    return {"case_id": case_id, "count": len(entries), "entries": [e.to_line() for e in entries]}


@router.get("/pepo/case/{case_id:path}/log/export", response_class=PlainTextResponse)
def export_case_log(case_id: str, case_log: CaseLogStore = Depends(get_case_log_store)) -> str:
    """Return the case log formatted as plain text, ready to paste into a ticket description."""
    return case_log.export_as_text(case_id)


@router.post("/pepo/case/{case_id:path}/close-to-ticket/{ticket_id}")
async def close_case_to_ticket(
    case_id: str,
    ticket_id: int,
    case_log: CaseLogStore = Depends(get_case_log_store),
    operations: AssetsOperationsService = Depends(get_operations_manager),
) -> dict[str, object]:
    """Export a case's log and append it to the given Assets ticket's description."""
    log_text = case_log.export_as_text(case_id)
    result = await operations.append_log_to_ticket(ticket_id, log_text)
    return {"case_id": case_id, "ticket_id": ticket_id, "result": result}
