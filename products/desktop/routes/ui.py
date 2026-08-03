"""Desktop product UI routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_DESKTOP_UI_ROOT = Path(__file__).resolve().parents[1] / "ui"
templates = Jinja2Templates(directory=str(_DESKTOP_UI_ROOT / "templates"))


def _resolve_session_user(request: Request) -> tuple[str | None, bool]:
    auth = getattr(request.app.state, "session_auth", None)
    if auth is None:
        return None, False
    token = request.cookies.get("session_token")
    if not token:
        return None, False
    username = auth.verificar_sesion(token)
    if not username:
        return None, False
    admin_username = "admin" if auth.existe_usuario("admin") else auth.primer_usuario()
    return username, username == admin_username


def _auth_guard(request: Request) -> RedirectResponse | None:
    """Redirect to /login if no valid session cookie is present.

    DESACTIVADO temporalmente a petición del usuario (login roto en WebView2,
    la petición POST /login nunca llega al servidor - pendiente de arreglar).
    """
    return None


def _page_context(
    request: Request,
    *,
    page_title: str,
    active_primary: str,
    active_admin: str | None = None,
) -> dict[str, object]:
    username, is_admin = _resolve_session_user(request)
    return {
        "request": request,
        "page_title": page_title,
        "current_user": username or "",
        "is_admin": is_admin,
        "active_primary": active_primary,
        "active_admin": active_admin or "",
    }


@router.get("/nexus-v1", response_class=HTMLResponse)
async def nexus_v1_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Operador", active_primary="operator")
    return templates.TemplateResponse("nexus_v1.html", context)


@router.get("/nexus-prompts", response_class=HTMLResponse)
async def nexus_prompts_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Prompting", active_primary="", active_admin="settings")
    return templates.TemplateResponse("nexus_prompts.html", context)


@router.get("/nexus-sales", response_class=HTMLResponse)
async def nexus_sales_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Sales", active_primary="sales")
    return templates.TemplateResponse("nexus_sales.html", context)


@router.get("/nexus-pepo", response_class=HTMLResponse)
async def nexus_pepo_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="PEPO", active_primary="pepo")
    return templates.TemplateResponse("nexus_pepo.html", context)


@router.get("/nexus/settings", response_class=HTMLResponse)
async def nexus_settings_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Configuracion", active_primary="", active_admin="settings")
    return templates.TemplateResponse("nexus_settings.html", context)


@router.get("/open-nexus", response_class=HTMLResponse)
async def open_nexus_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Shell", active_primary="shell")
    return templates.TemplateResponse("open_nexus.html", context)


@router.get("/open-nexus/models", response_class=HTMLResponse)
async def open_nexus_models_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Modelos", active_primary="", active_admin="settings")
    return templates.TemplateResponse("open_nexus_models.html", context)


@router.get("/nexus/vault", response_class=HTMLResponse)
async def nexus_vault_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Vault", active_primary="", active_admin="vault")
    return templates.TemplateResponse("nexus_vault.html", context)


@router.get("/nexus/campaign", response_class=HTMLResponse)
async def nexus_campaign_page(request: Request):
    if (r := _auth_guard(request)) is not None:
        return r
    context = _page_context(request, page_title="Campaña", active_primary="", active_admin="campaign")
    return templates.TemplateResponse("nexus_campaign.html", context)
