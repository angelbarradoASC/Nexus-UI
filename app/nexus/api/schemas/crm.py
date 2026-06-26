"""Schemas for CRM bridge routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CRMStatusResponse(BaseModel):
    status: str
    provider: str
    discovered_source: str
    connector: dict[str, Any]
    campaigns_total: int
    pending_prospects: int
    recent_campaigns: list[dict[str, Any]]


class CRMSyncRequest(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=3, ge=1, le=20)


class CRMSyncResponse(BaseModel):
    status: str
    campaign_id: str
    dry_run: bool
    synced_count: int
    results: list[dict[str, Any]]


class CRMInboundMailRequest(BaseModel):
    dry_run: bool = True
    create_company_if_missing: bool = True
    message: dict[str, Any]


class CRMInboundMailResponse(BaseModel):
    status: str
    dry_run: bool
    result: dict[str, Any]
