"""CRM routes for Nexus v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nexus.api.dependencies.auth import get_crm_manager
from nexus.api.schemas.crm import (
    CRMInboundMailRequest,
    CRMInboundMailResponse,
    CRMSyncRequest,
    CRMSyncResponse,
    CRMStatusResponse,
)
from nexus.crm import CRMBridgeService

router = APIRouter()


@router.get("/crm/status", response_model=CRMStatusResponse)
async def get_crm_status(
    crm: CRMBridgeService = Depends(get_crm_manager),
) -> CRMStatusResponse:
    return await crm.status()


@router.post("/crm/campaigns/{campaign_id}/sync", response_model=CRMSyncResponse)
async def sync_campaign_to_crm(
    campaign_id: str,
    payload: CRMSyncRequest,
    crm: CRMBridgeService = Depends(get_crm_manager),
) -> CRMSyncResponse:
    result = await crm.sync_campaign(campaign_id, dry_run=payload.dry_run, limit=payload.limit)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return result


@router.post("/crm/mail/ingest", response_model=CRMInboundMailResponse)
async def ingest_mail_into_crm(
    payload: CRMInboundMailRequest,
    crm: CRMBridgeService = Depends(get_crm_manager),
) -> CRMInboundMailResponse:
    result = await crm.ingest_inbound_mail(
        payload.message,
        dry_run=payload.dry_run,
        create_company_if_missing=payload.create_company_if_missing,
    )
    return {
        "status": result.get("status", "error"),
        "dry_run": payload.dry_run,
        "result": result,
    }
