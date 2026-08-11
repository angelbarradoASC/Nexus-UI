"""CRUD de configuración persistida de Desktop: proveedor/router LLM, ventas,
campaña/outreach, ITSM, e integraciones de monitorización.

`bootstrap_desktop_config()` es el único punto de entrada que aplica toda
esta configuración sobre `cfg` al arrancar (antes eran 4 llamadas sueltas a
nivel de módulo en `app.py`). Los handlers de ruta reciben `DesktopSettings`/
`DesktopLocalState` ya cacheados vía `Depends` — no se reconstruyen por
petición (ver `dependencies.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from config import cfg
from desktop.config import DesktopSettings
from desktop.runtime.llm_provider_runtime import apply_desktop_provider_to_cfg, apply_desktop_router_config
from desktop.storage.local_state import DesktopLocalState
from desktop.storage.monitoring_integrations import (
    DesktopMonitoringIntegration,
    DesktopMonitoringIntegrationStore,
)
from desktop.storage.provider_config import DesktopLLMProviderConfig
from desktop.storage.router_config import DesktopLLMRouterConfig, LLMLevelConfig
from nexus.api.dependencies.auth import build_runtime, upgrade_runtime_with_app_state
from nexus.connectors.observability.alertmanager import AlertmanagerConnector
from nexus.connectors.observability.grafana import GrafanaConnector
from nexus.connectors.observability.prometheus import PrometheusConnector
from products.desktop.backend.dependencies import get_desktop_local_state, get_desktop_settings

router = APIRouter()


# ── Bootstrap: aplicar config persistida sobre cfg (una vez, al arrancar) ────

def _load_desktop_provider_config(local_state: DesktopLocalState) -> DesktopLLMProviderConfig:
    return local_state.load_llm_provider_config()


def _apply_desktop_provider_config(local_state: DesktopLocalState) -> DesktopLLMProviderConfig:
    provider_config = _load_desktop_provider_config(local_state)
    apply_desktop_provider_to_cfg(cfg, provider_config)
    return provider_config


def _load_desktop_router_config(local_state: DesktopLocalState) -> DesktopLLMRouterConfig | None:
    return local_state.load_llm_router_config()


def _apply_desktop_startup_config(local_state: DesktopLocalState) -> None:
    """llm_router.json tiene prioridad sobre llm_provider.json."""
    router_config = _load_desktop_router_config(local_state)
    if router_config and router_config.has_any_level:
        apply_desktop_router_config(cfg, router_config)
    else:
        _apply_desktop_provider_config(local_state)


def _apply_desktop_sales_config(cfg, data: dict | None) -> None:
    if data is None:
        return
    brave = data.get("brave", {})
    if "enabled" in brave:
        cfg.brave_search_enabled = bool(brave["enabled"])
    if brave.get("api_key"):
        cfg.brave_search_api_key = brave["api_key"]
    if "rate_limit" in brave:
        cfg.brave_search_rate_limit = float(brave["rate_limit"])
    gp = data.get("google_places", {})
    if "enabled" in gp:
        cfg.google_places_enabled = bool(gp["enabled"])
    if gp.get("api_key"):
        cfg.google_places_api_key = gp["api_key"]
    if "rate_limit" in gp:
        cfg.google_places_rate_limit = float(gp["rate_limit"])
    if "max_results" in gp:
        cfg.google_places_max_results_per_query = int(gp["max_results"])
    assets = data.get("assets_crm", {})
    if "enabled" in assets:
        cfg.assets_crm_enabled = bool(assets["enabled"])
    if assets.get("base_url"):
        cfg.assets_crm_base_url = assets["base_url"]
    if assets.get("username"):
        cfg.assets_crm_username = assets["username"]
    if assets.get("password"):
        cfg.assets_crm_password = assets["password"]
    odoo = data.get("odoo", {})
    if "enabled" in odoo:
        cfg.crm_odoo_enabled = bool(odoo["enabled"])
    if odoo.get("base_url"):
        cfg.crm_odoo_base_url = odoo["base_url"]
    if odoo.get("database"):
        cfg.crm_odoo_database = odoo["database"]
    if odoo.get("username"):
        cfg.crm_odoo_username = odoo["username"]
    if odoo.get("password"):
        cfg.crm_odoo_password = odoo["password"]
    if odoo.get("default_team") is not None:
        cfg.crm_odoo_default_team = odoo["default_team"]
    if odoo.get("default_stage") is not None:
        cfg.crm_odoo_default_stage = odoo["default_stage"]


def _apply_desktop_campaign_config(cfg, data: dict | None) -> None:
    if data is None:
        return
    outreach = data.get("outreach", {})
    if "enabled" in outreach:
        cfg.outreach_enabled = bool(outreach["enabled"])
    if outreach.get("from_address") is not None:
        cfg.outreach_email_address = outreach["from_address"]
    if outreach.get("sender_name") is not None:
        cfg.outreach_sender_name = outreach["sender_name"]
    if "daily_cap" in outreach:
        cfg.outreach_daily_cap_default = int(outreach["daily_cap"])
    if outreach.get("followup_delays") is not None:
        cfg.outreach_followup_delays_days = outreach["followup_delays"]
    smtp = data.get("smtp", {})
    if smtp.get("host") is not None:
        cfg.outreach_smtp_host = smtp["host"]
    if "port" in smtp:
        cfg.outreach_smtp_port = int(smtp["port"])
    if smtp.get("user") is not None:
        cfg.outreach_smtp_user = smtp["user"]
    if smtp.get("password"):
        cfg.outreach_smtp_password = smtp["password"]
    imap = data.get("imap", {})
    if imap.get("host") is not None:
        cfg.outreach_imap_host = imap["host"]
    if "port" in imap:
        cfg.outreach_imap_port = int(imap["port"])
    if imap.get("user") is not None:
        cfg.outreach_imap_user = imap["user"]
    if imap.get("password"):
        cfg.outreach_imap_password = imap["password"]


def _apply_desktop_itsm_config(config, data: dict | None) -> None:
    if not data:
        return
    assets = data.get("assets", {})
    jira = data.get("jira", {})
    sn = data.get("servicenow", {})
    if assets.get("enabled") is not None:
        config.assets_itsm_enabled = bool(assets["enabled"])
    if jira.get("enabled") is not None:
        config.use_jira = bool(jira["enabled"])
    if jira.get("url") is not None:
        config.jira_url = jira["url"]
    if jira.get("email") is not None:
        config.jira_email = jira["email"]
    if jira.get("api_token"):
        config.jira_api_token = jira["api_token"]
    if jira.get("project_key") is not None:
        config.jira_project_key = jira["project_key"] or "NEXUS"
    if sn.get("enabled") is not None:
        config.use_servicenow = bool(sn["enabled"])
    if sn.get("url") is not None:
        config.servicenow_url = sn["url"]
    if sn.get("username") is not None:
        config.servicenow_username = sn["username"]
    if sn.get("password"):
        config.servicenow_password = sn["password"]
    if sn.get("client_id") is not None:
        config.servicenow_client_id = sn["client_id"]
    if sn.get("client_secret"):
        config.servicenow_client_secret = sn["client_secret"]


def bootstrap_desktop_config(cfg, local_state: DesktopLocalState) -> None:
    """Único punto de entrada para aplicar toda la config persistida de
    Desktop sobre `cfg` al arrancar."""
    _apply_desktop_startup_config(local_state)
    _apply_desktop_sales_config(cfg, local_state.load_sales_config())
    _apply_desktop_campaign_config(cfg, local_state.load_campaign_config())
    _apply_desktop_itsm_config(cfg, local_state.load_itsm_config())


def _get_monitoring_store(settings: DesktopSettings) -> DesktopMonitoringIntegrationStore:
    return DesktopMonitoringIntegrationStore(settings.monitoring_config_db_path)


async def _reload_desktop_provider_runtime(request: Request, local_state: DesktopLocalState) -> DesktopLLMProviderConfig:
    from agents.llm_router import get_router, reset_router

    provider_config = _apply_desktop_provider_config(local_state)
    await reset_router()
    request.app.state.llm_router = get_router()
    request.app.state.nexus_runtime = build_runtime(cfg)
    upgrade_runtime_with_app_state(request.app, cfg)
    return provider_config


async def _reload_desktop_monitoring_runtime(request: Request) -> None:
    request.app.state.nexus_runtime = build_runtime(cfg)
    upgrade_runtime_with_app_state(request.app, cfg)


# ── LLM provider (activo actual) ─────────────────────────────────────────────

class _DesktopProviderConfigBody(BaseModel):
    provider_type: str = "openai_compatible"
    provider_label: str = "Servidor remoto"
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = False


@router.get("/api/desktop/providers")
async def get_desktop_provider_config(local_state: DesktopLocalState = Depends(get_desktop_local_state)):
    provider_config = _load_desktop_provider_config(local_state)
    return {
        "available": True,
        "provider": provider_config.to_dict(mask_secret=True),
        "configured": provider_config.is_configured,
        "applied": provider_config.enabled and provider_config.is_configured,
    }


@router.put("/api/desktop/providers")
async def save_desktop_provider_config(
    request: Request,
    body: _DesktopProviderConfigBody,
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    existing_config = local_state.load_llm_provider_config()
    incoming = body.model_dump()
    if not incoming.get("api_key"):
        incoming["api_key"] = existing_config.api_key

    saved_config = local_state.save_llm_provider_config(DesktopLLMProviderConfig.from_dict(incoming))
    applied_config = await _reload_desktop_provider_runtime(request, local_state)
    return {
        "available": True,
        "status": "saved",
        "provider": saved_config.to_dict(mask_secret=True),
        "applied": applied_config.enabled and applied_config.is_configured,
        "paths": {
            "config_dir": str(local_state.config_dir),
            "provider_file": str(local_state.llm_provider_config_path),
        },
    }


# ── LLM router (tabla L0-L3) ──────────────────────────────────────────────────

class _LLMLevelBody(BaseModel):
    url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = True


class _DesktopLLMRouterBody(BaseModel):
    priority: str = "cost"
    l0: _LLMLevelBody = _LLMLevelBody()
    l1: _LLMLevelBody = _LLMLevelBody()
    l2: _LLMLevelBody = _LLMLevelBody()
    l3: _LLMLevelBody = _LLMLevelBody()


@router.get("/api/desktop/llm-router")
async def get_llm_router_config(local_state: DesktopLocalState = Depends(get_desktop_local_state)):
    from agents.llm_router import get_router

    saved = local_state.load_llm_router_config()
    router_dict = saved.to_dict(mask_keys=True) if saved else DesktopLLMRouterConfig.from_app_config(cfg).to_dict(mask_keys=True)
    watchdog = get_router().watchdog_snapshot() if get_router()._watchdog else {"enabled": False}
    health_by_level = {}
    if watchdog.get("enabled"):
        for lv_info in watchdog.get("levels", {}).values():
            num = lv_info.get("level", -1)
            health_by_level[str(num)] = lv_info.get("healthy", False)
    return {
        "router": router_dict,
        "health": health_by_level,
        "source": "saved" if saved else "env_defaults",
        "path": str(local_state.llm_router_config_path),
    }


@router.put("/api/desktop/llm-router")
async def save_llm_router_config(
    request: Request,
    body: _DesktopLLMRouterBody,
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    from agents.llm_router import get_router, reset_router

    existing = local_state.load_llm_router_config()

    def _merge_key(new_key: str, existing_level, level_attr: str) -> str:
        if new_key:
            return new_key
        if existing:
            return getattr(existing, level_attr).api_key
        return ""

    router_config = DesktopLLMRouterConfig(
        priority=body.priority,
        l0=LLMLevelConfig(url=body.l0.url, model=body.l0.model, enabled=body.l0.enabled, api_key=_merge_key(body.l0.api_key, existing, "l0")),
        l1=LLMLevelConfig(url=body.l1.url, model=body.l1.model, enabled=body.l1.enabled, api_key=_merge_key(body.l1.api_key, existing, "l1")),
        l2=LLMLevelConfig(url=body.l2.url, model=body.l2.model, enabled=body.l2.enabled, api_key=_merge_key(body.l2.api_key, existing, "l2")),
        l3=LLMLevelConfig(url=body.l3.url, model=body.l3.model, enabled=body.l3.enabled, api_key=_merge_key(body.l3.api_key, existing, "l3")),
    )
    saved = local_state.save_llm_router_config(router_config)
    apply_desktop_router_config(cfg, saved)
    await reset_router()
    request.app.state.llm_router = get_router()
    request.app.state.nexus_runtime = build_runtime(cfg)
    upgrade_runtime_with_app_state(request.app, cfg)
    return {"status": "saved", "router": saved.to_dict(mask_keys=True), "path": str(local_state.llm_router_config_path)}


# ── Integraciones de monitorización ──────────────────────────────────────────

class _DesktopMonitoringIntegrationBody(BaseModel):
    integration_id: str | None = None
    kind: str
    name: str
    base_url: str
    enabled: bool = True
    is_default: bool = False
    auth_type: str = "none"
    username: str = ""
    secret_ref: str = ""
    header_name: str = ""
    verify_tls: bool = True
    timeout_seconds: int | None = None
    source: str = "manual"


@router.get("/api/desktop/operator/integrations")
async def list_desktop_monitoring_integrations(settings: DesktopSettings = Depends(get_desktop_settings)):
    store = _get_monitoring_store(settings)
    store.migrate_from_cfg(cfg)
    integrations = [item.to_dict() for item in store.list_integrations()]
    return {
        "available": True,
        "integrations": integrations,
        "defaults": {
            kind: (store.get_default(kind).integration_id if store.get_default(kind) else None)
            for kind in ("prometheus", "grafana", "alertmanager")
        },
        "paths": {"config_db": str(settings.monitoring_config_db_path)},
    }


@router.put("/api/desktop/operator/integrations")
async def save_desktop_monitoring_integration(
    request: Request,
    body: _DesktopMonitoringIntegrationBody,
    settings: DesktopSettings = Depends(get_desktop_settings),
):
    store = _get_monitoring_store(settings)
    integration = DesktopMonitoringIntegration.create(
        integration_id=body.integration_id, kind=body.kind, name=body.name, base_url=body.base_url,
        enabled=body.enabled, is_default=body.is_default, auth_type=body.auth_type, username=body.username,
        secret_ref=body.secret_ref, header_name=body.header_name, verify_tls=body.verify_tls,
        timeout_seconds=body.timeout_seconds, source=body.source,
    )
    saved = store.save_integration(integration)
    await _reload_desktop_monitoring_runtime(request)
    return {
        "available": True,
        "status": "saved",
        "integration": saved.to_dict(),
        "paths": {"config_db": str(settings.monitoring_config_db_path)},
    }


@router.post("/api/desktop/operator/integrations/test")
async def test_desktop_monitoring_integration(body: _DesktopMonitoringIntegrationBody):
    timeout_seconds = body.timeout_seconds or cfg.connector_timeout_seconds
    base_url = body.base_url.strip().rstrip("/")

    if body.kind == "prometheus":
        connector = PrometheusConnector(base_url, timeout_seconds=timeout_seconds)
    elif body.kind == "grafana":
        connector = GrafanaConnector(base_url, timeout_seconds=timeout_seconds)
    elif body.kind == "alertmanager":
        connector = AlertmanagerConnector(base_url, timeout_seconds=timeout_seconds)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Test de conectividad no soportado todavia para este tipo")

    try:
        report = await connector.healthcheck()
        return {"available": True, "status": "ok", "report": report}
    except Exception as exc:
        return {
            "available": True,
            "status": "error",
            "report": {"name": body.name, "kind": body.kind, "endpoint": base_url, "reason": str(exc)},
        }


@router.delete("/api/desktop/operator/integrations/{integration_id}")
async def delete_desktop_monitoring_integration(
    request: Request,
    integration_id: str,
    settings: DesktopSettings = Depends(get_desktop_settings),
):
    store = _get_monitoring_store(settings)
    deleted = store.delete_integration(integration_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integracion no encontrada")
    await _reload_desktop_monitoring_runtime(request)
    return {"available": True, "status": "deleted", "integration_id": integration_id}


# ── Ventas (Brave/Google Places/Assets CRM/Odoo) ─────────────────────────────

@router.get("/api/desktop/settings/sales")
async def get_desktop_sales_config():
    return {
        "available": True,
        "source": "runtime",
        "brave": {
            "enabled": cfg.brave_search_enabled,
            "api_key_set": bool(cfg.brave_search_api_key),
            "rate_limit": cfg.brave_search_rate_limit,
        },
        "google_places": {
            "enabled": cfg.google_places_enabled,
            "api_key_set": bool(cfg.google_places_api_key),
            "rate_limit": cfg.google_places_rate_limit,
            "max_results": cfg.google_places_max_results_per_query,
        },
        "assets_crm": {
            "enabled": cfg.assets_crm_enabled,
            "base_url": cfg.assets_crm_base_url,
            "username": cfg.assets_crm_username,
            "password_set": bool(cfg.assets_crm_password),
        },
        "odoo": {
            "enabled": cfg.crm_odoo_enabled,
            "base_url": cfg.crm_odoo_base_url,
            "database": cfg.crm_odoo_database,
            "username": cfg.crm_odoo_username,
            "password_set": bool(cfg.crm_odoo_password),
            "default_team": cfg.crm_odoo_default_team,
            "default_stage": cfg.crm_odoo_default_stage,
        },
    }


class _DesktopSalesConfigBody(BaseModel):
    brave_enabled: bool = False
    brave_api_key: str = ""
    brave_rate_limit: float = 1.0
    gp_enabled: bool = False
    gp_api_key: str = ""
    gp_rate_limit: float = 0.5
    gp_max_results: int = 20
    assets_crm_enabled: bool = True
    assets_crm_base_url: str = ""
    assets_crm_username: str = ""
    assets_crm_password: str = ""
    odoo_enabled: bool = True
    odoo_base_url: str = ""
    odoo_database: str = ""
    odoo_username: str = ""
    odoo_password: str = ""
    odoo_default_team: str = ""
    odoo_default_stage: str = ""


@router.put("/api/desktop/settings/sales")
async def save_desktop_sales_config(
    body: _DesktopSalesConfigBody,
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    existing = local_state.load_sales_config() or {}
    ex_brave = existing.get("brave", {})
    ex_gp = existing.get("google_places", {})
    ex_assets = existing.get("assets_crm", {})
    ex_odoo = existing.get("odoo", {})

    def _keep(new_val: str, old_val: str) -> str:
        return new_val if new_val else (old_val or "")

    data = {
        "brave": {"enabled": body.brave_enabled, "api_key": _keep(body.brave_api_key, ex_brave.get("api_key", "")), "rate_limit": body.brave_rate_limit},
        "google_places": {
            "enabled": body.gp_enabled, "api_key": _keep(body.gp_api_key, ex_gp.get("api_key", "")),
            "rate_limit": body.gp_rate_limit, "max_results": body.gp_max_results,
        },
        "assets_crm": {
            "enabled": body.assets_crm_enabled, "base_url": body.assets_crm_base_url, "username": body.assets_crm_username,
            "password": _keep(body.assets_crm_password, ex_assets.get("password", "")),
        },
        "odoo": {
            "enabled": body.odoo_enabled, "base_url": body.odoo_base_url, "database": body.odoo_database,
            "username": body.odoo_username, "password": _keep(body.odoo_password, ex_odoo.get("password", "")),
            "default_team": body.odoo_default_team, "default_stage": body.odoo_default_stage,
        },
    }
    saved = local_state.save_sales_config(data)
    _apply_desktop_sales_config(cfg, saved)
    return {"status": "saved", "path": str(local_state.settings.sales_config_path)}


# ── Campaña / outreach ────────────────────────────────────────────────────────

@router.get("/api/desktop/settings/campaign")
async def get_desktop_campaign_config():
    return {
        "available": True,
        "source": "runtime",
        "outreach": {
            "enabled": cfg.outreach_enabled,
            "from_address": cfg.outreach_email_address,
            "sender_name": cfg.outreach_sender_name,
            "daily_cap": cfg.outreach_daily_cap_default,
            "followup_delays": cfg.outreach_followup_delays_days,
        },
        "smtp": {
            "host": cfg.outreach_smtp_host,
            "port": cfg.outreach_smtp_port,
            "user": cfg.outreach_smtp_user,
            "password_set": bool(cfg.outreach_smtp_password),
        },
        "imap": {
            "host": cfg.outreach_imap_host,
            "port": cfg.outreach_imap_port,
            "user": cfg.outreach_imap_user,
            "password_set": bool(cfg.outreach_imap_password),
        },
    }


class _DesktopCampaignConfigBody(BaseModel):
    outreach_enabled: bool = False
    outreach_from_address: str = ""
    outreach_sender_name: str = ""
    outreach_daily_cap: int = 20
    outreach_followup_delays: str = "4,9"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""


@router.put("/api/desktop/settings/campaign")
async def save_desktop_campaign_config(
    body: _DesktopCampaignConfigBody,
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    existing = local_state.load_campaign_config() or {}
    ex_smtp = existing.get("smtp", {})
    ex_imap = existing.get("imap", {})

    def _keep(new_val: str, old_val: str) -> str:
        return new_val if new_val else (old_val or "")

    data = {
        "outreach": {
            "enabled": body.outreach_enabled, "from_address": body.outreach_from_address,
            "sender_name": body.outreach_sender_name, "daily_cap": body.outreach_daily_cap,
            "followup_delays": body.outreach_followup_delays,
        },
        "smtp": {
            "host": body.smtp_host, "port": body.smtp_port, "user": body.smtp_user,
            "password": _keep(body.smtp_password, ex_smtp.get("password", "")),
        },
        "imap": {
            "host": body.imap_host, "port": body.imap_port, "user": body.imap_user,
            "password": _keep(body.imap_password, ex_imap.get("password", "")),
        },
    }
    saved = local_state.save_campaign_config(data)
    _apply_desktop_campaign_config(cfg, saved)
    return {"status": "saved", "path": str(local_state.settings.campaign_config_path)}


# ── ITSM (Assets/Jira/ServiceNow) ─────────────────────────────────────────────

@router.get("/api/desktop/settings/itsm")
async def get_desktop_itsm_config():
    return {
        "available": True,
        "source": "runtime",
        "assets": {
            "enabled": cfg.assets_itsm_enabled,
            "base_url": cfg.assets_crm_base_url,
            "username": cfg.assets_crm_username,
            "password_set": bool(cfg.assets_crm_password),
        },
        "jira": {
            "enabled": cfg.use_jira,
            "url": cfg.jira_url,
            "email": cfg.jira_email,
            "api_token_set": bool(cfg.jira_api_token),
            "project_key": cfg.jira_project_key,
        },
        "servicenow": {
            "enabled": cfg.use_servicenow,
            "url": cfg.servicenow_url,
            "username": cfg.servicenow_username,
            "password_set": bool(cfg.servicenow_password),
            "client_id": cfg.servicenow_client_id,
            "client_secret_set": bool(cfg.servicenow_client_secret),
        },
    }


class _DesktopItsmConfigBody(BaseModel):
    assets_enabled: bool = True
    assets_base_url: str = ""
    assets_username: str = ""
    assets_password: str = ""
    jira_enabled: bool = False
    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "NEXUS"
    sn_enabled: bool = False
    sn_url: str = ""
    sn_username: str = ""
    sn_password: str = ""
    sn_client_id: str = ""
    sn_client_secret: str = ""


@router.put("/api/desktop/settings/itsm")
async def save_desktop_itsm_config(
    body: _DesktopItsmConfigBody,
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    existing = local_state.load_itsm_config() or {}
    ex_assets = existing.get("assets", {})
    ex_jira = existing.get("jira", {})
    ex_sn = existing.get("servicenow", {})

    def _keep(new_val: str, old_val: str) -> str:
        return new_val if new_val else (old_val or "")

    data = {
        "assets": {
            "enabled": body.assets_enabled, "base_url": body.assets_base_url, "username": body.assets_username,
            "password": _keep(body.assets_password, ex_assets.get("password", "")),
        },
        "jira": {
            "enabled": body.jira_enabled, "url": body.jira_url, "email": body.jira_email,
            "api_token": _keep(body.jira_api_token, ex_jira.get("api_token", "")),
            "project_key": body.jira_project_key or "NEXUS",
        },
        "servicenow": {
            "enabled": body.sn_enabled, "url": body.sn_url, "username": body.sn_username,
            "password": _keep(body.sn_password, ex_sn.get("password", "")),
            "client_id": body.sn_client_id,
            "client_secret": _keep(body.sn_client_secret, ex_sn.get("client_secret", "")),
        },
    }
    saved = local_state.save_itsm_config(data)
    _apply_desktop_itsm_config(cfg, saved)
    return {"status": "saved", "path": str(local_state.settings.itsm_config_path)}
