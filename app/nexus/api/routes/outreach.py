"""Outreach routes for Nexus v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nexus.api.dependencies.auth import get_outreach_manager
from nexus.api.schemas.outreach import (
    OutreachCampaignListResponse,
    OutreachEventListResponse,
    OutreachLaunchRequest,
    OutreachLaunchResponse,
    OutreachRunDueRequest,
    OutreachStatusResponse,
)
from nexus.outreach import OutreachManager

router = APIRouter()


@router.get("/outreach/status", response_model=OutreachStatusResponse)
async def get_outreach_status(
    outreach: OutreachManager = Depends(get_outreach_manager),
) -> OutreachStatusResponse:
    """Expose the current outreach mailbox and campaign status."""
    return await outreach.status()


@router.get("/outreach/campaigns", response_model=OutreachCampaignListResponse)
async def get_outreach_campaigns(
    outreach: OutreachManager = Depends(get_outreach_manager),
) -> OutreachCampaignListResponse:
    """List recent outreach campaigns."""
    return await outreach.list_campaigns()


@router.get("/outreach/events", response_model=OutreachEventListResponse)
async def get_outreach_events(
    outreach: OutreachManager = Depends(get_outreach_manager),
) -> OutreachEventListResponse:
    """List recent outreach delivery events."""
    return await outreach.list_events()


@router.post("/outreach/launch", response_model=OutreachLaunchResponse)
async def launch_outreach_campaign(
    payload: OutreachLaunchRequest,
    outreach: OutreachManager = Depends(get_outreach_manager),
) -> OutreachLaunchResponse:
    """Create a campaign and execute its current due batch."""
    try:
        return await outreach.launch_campaign(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/outreach/campaigns/{campaign_id}/run-due", response_model=OutreachLaunchResponse)
async def run_due_outreach_campaign(
    campaign_id: str,
    payload: OutreachRunDueRequest,
    outreach: OutreachManager = Depends(get_outreach_manager),
) -> OutreachLaunchResponse:
    """Run the next due batch for an existing campaign."""
    result = await outreach.run_campaign(campaign_id, dry_run=payload.dry_run)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return result
