"""Schemas for the Nexus outreach agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OutreachProspectIn(BaseModel):
    """Single prospect payload for B2B outreach."""

    email: str = Field(min_length=5)
    first_name: str = ""
    company: str = ""
    job_title: str = ""
    company_domain: str = ""
    notes: str = ""


class OutreachLaunchRequest(BaseModel):
    """Launch a low-volume B2B outreach campaign."""

    campaign_name: str = Field(min_length=3)
    proposition: str = Field(min_length=8)
    cta: str | None = None
    audience_hint: str | None = None
    sender_name: str | None = None
    max_daily_send: int | None = Field(default=None, ge=1, le=50)
    followup_delays_days: list[int] | None = None
    dry_run: bool = True
    prospects: list[OutreachProspectIn] = Field(default_factory=list)
    csv_text: str | None = None
    json_text: str | None = None


class OutreachRunDueRequest(BaseModel):
    """Execute the next due batch of a campaign."""

    dry_run: bool = True


class OutreachStatusResponse(BaseModel):
    """Status snapshot for the outreach surface."""

    status: str
    enabled: bool
    account: dict[str, Any]
    daily_cap_default: int
    sent_today: int
    campaigns_total: int
    recent_campaigns: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]


class OutreachCampaignListResponse(BaseModel):
    """Recent campaigns for the outreach UI."""

    status: str
    total: int
    campaigns: list[dict[str, Any]]


class OutreachEventListResponse(BaseModel):
    """Recent outreach events for the UI."""

    status: str
    total: int
    events: list[dict[str, Any]]


class OutreachLaunchResponse(BaseModel):
    """Response after a campaign is accepted."""

    status: str
    campaign_id: str
    dry_run: bool
    executed_count: int
    total_prospects: int
    events: list[dict[str, Any]]
