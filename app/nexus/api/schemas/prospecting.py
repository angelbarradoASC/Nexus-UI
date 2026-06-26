"""Schemas for generalized prospecting routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProspectingRunRequest(BaseModel):
    vertical: str = Field(default="custom")
    target_description: str = ""
    city: str = ""
    province: str = ""
    region: str = ""
    radius_km: int | None = Field(default=None, ge=1, le=250)
    desired_count: int = Field(default=20, ge=1, le=100)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    crm_tags: list[str] = Field(default_factory=list)
    campaign_type: str = ""
    minimum_score: int = Field(default=40, ge=0, le=100)
    country: str = "es"
    language: str = "es"
    dry_run: bool = True
    async_mode: bool = False
    represented_by: str = Field(default="assets", pattern=r"^(assets|automato|other)$")


class ProspectingRunResponse(BaseModel):
    status: str
    run_id: str
    summary: dict[str, Any]
    results_count: int
    discarded_count: int
    dry_run: bool
    queries: list[str] = Field(default_factory=list)
    orchestration: dict[str, Any] | None = None


class ProspectingRunDetailResponse(BaseModel):
    status: str
    run_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    brief: dict[str, Any] | None = None
    queries: list[str] = Field(default_factory=list)
    summary: dict[str, Any] | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    discarded: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    runtime: dict[str, Any] | None = None
    orchestration: dict[str, Any] | None = None


class ProspectingResultListResponse(BaseModel):
    status: str
    results: list[dict[str, Any]]


class ProspectingDiscardedListResponse(BaseModel):
    status: str
    discarded: list[dict[str, Any]]


class ProspectingPushRequest(BaseModel):
    dry_run: bool = True
    run_id: str | None = None


class ProspectingPushResponse(BaseModel):
    status: str
    message: str | None = None
    dry_run: bool | None = None
    result_id: str | None = None
    run_id: str | None = None
    pushed_count: int | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    company_id: int | None = None
    company_name: str | None = None
    reused: bool | None = None
    company_payload: dict[str, Any] | None = None
    pipeline_payload: dict[str, Any] | None = None
    note_payload: dict[str, Any] | None = None
