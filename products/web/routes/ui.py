"""Canonical UI routes for the legacy web product surface.

Important:
- Nexus Desktop lives in ``products.desktop``.
- These routes exist only for the browser-oriented legacy stack.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_WEB_UI_ROOT = Path(__file__).resolve().parents[1] / "ui"
templates = Jinja2Templates(directory=str(_WEB_UI_ROOT / "templates"))


@router.get("/nexus-v1", response_class=HTMLResponse)
async def nexus_v1_page(request: Request):
    """Browser entrypoint for reviewing the Nexus v1 surface."""
    return templates.TemplateResponse("nexus_v1.html", {"request": request})


@router.get("/nexus-prompts", response_class=HTMLResponse)
async def nexus_prompts_page(request: Request):
    """Browser entrypoint for editing live Nexus prompts."""
    return templates.TemplateResponse("nexus_prompts.html", {"request": request})


@router.get("/nexus-sales", response_class=HTMLResponse)
async def nexus_sales_page(request: Request):
    """Browser entrypoint for the commercial outreach and CRM surface."""
    return templates.TemplateResponse("nexus_sales.html", {"request": request})


@router.get("/open-nexus", response_class=HTMLResponse)
async def open_nexus_page(request: Request):
    """Legacy browser shell surface for Open-Nexus."""
    return templates.TemplateResponse("open_nexus.html", {"request": request})


@router.get("/open-nexus/models", response_class=HTMLResponse)
async def open_nexus_models_page(request: Request):
    """Legacy browser configuration page for remote LLM endpoints."""
    return templates.TemplateResponse("open_nexus_models.html", {"request": request})


@router.get("/nexus/vault", response_class=HTMLResponse)
async def nexus_vault_page(request: Request):
    """Legacy browser vault surface."""
    return templates.TemplateResponse("nexus_vault.html", {"request": request})
