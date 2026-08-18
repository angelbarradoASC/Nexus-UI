"""
desktop/local_agents/self_config_agent.py
--------------------------------------------
SelfConfigAgent — permite a PEPO auto-configurar integraciones reales por
chat: dar de alta credenciales en el Vault (opcionalmente dando de alta el
dispositivo en el CMDB si es nuevo) y configurar la conexion a un CRM
(Assets u Odoo, los dos que Sales ya soporta). Sobre ConfirmableAgent
(confirmable_loop.py) — el bucle de tool-calling, la gestion de pendientes
y la heuristica de ask_user_secret son compartidos con RemoteOpsAgent; aqui
solo viven las tools propias y que hacer con ellas.

Para lo que no esta soportado (un proveedor de CRM que no sea assets_crm/
odoo, por ejemplo) se responde con honestidad, no se inventa.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from desktop.local_agents.confirmable_loop import ConfirmableAgent, PendingAction, ProposalOutcome

logger = logging.getLogger("nexus.self_config_agent")

_SUPPORTED_CRM_PROVIDERS = {"assets_crm", "odoo"}

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_cmdb",
            "description": (
                "Busca un dispositivo real en el CMDB de Nexus por nombre, IP, tipo o "
                "notas. Usalo SIEMPRE antes de asumir que un dispositivo no existe — si "
                "no aparece, es candidato a darlo de alta con propose_store_credential."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Nombre o pista del dispositivo, tal como lo dijo el usuario."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_credentials",
            "description": (
                "Comprueba si ya hay credenciales guardadas en el Vault para un "
                "device_id ya resuelto por lookup_cmdb. Nunca devuelve el secreto."
            ),
            "parameters": {
                "type": "object",
                "properties": {"device_id": {"type": "string"}},
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_store_credential",
            "description": (
                "Propone guardar credenciales en el Vault para un dispositivo. Si el "
                "dispositivo no aparecio en lookup_cmdb, incluye device_name/ip/"
                "device_type/management_protocol para darlo de alta a la vez. "
                "Pendiente de confirmacion humana — NUNCA escribe nada todavia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "device_id ya resuelto por lookup_cmdb, si existe."},
                    "device_name": {"type": "string", "description": "Nombre legible del dispositivo — para el mensaje de confirmacion y para darlo de alta si es nuevo."},
                    "ip": {"type": "string", "description": "IP del dispositivo, solo si es nuevo (no esta en el CMDB)."},
                    "device_type": {"type": "string", "description": "server|switch|router|firewall|windows|appliance|unknown — solo si es nuevo."},
                    "management_protocol": {"type": "string", "description": "ssh|winrm|rest_api|snmp|none — solo si es nuevo."},
                    "auth_method": {"type": "string", "description": "password|ssh_key|api_token"},
                    "username": {"type": "string"},
                    "secret": {"type": "string", "description": "La contraseña o token, ya obtenido via ask_user_secret."},
                    "ssh_key": {"type": "string", "description": "Clave SSH PEM completa, solo si auth_method=ssh_key."},
                },
                "required": ["device_name", "auth_method", "username", "secret"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crm_config",
            "description": "Consulta la configuracion actual de CRM (Assets CRM y Odoo). Nunca revela secretos, solo si estan puestos.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_set_crm_config",
            "description": (
                "Propone configurar la conexion a un CRM. Si el usuario no especifico "
                "cual (Sales soporta Assets CRM y Odoo a la vez), pregunta con ask_user "
                "antes de llamar a esto — no asumas cual. Pendiente de confirmacion — "
                "NUNCA escribe nada todavia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "'assets_crm' u 'odoo' — no hay mas proveedores soportados hoy, no inventes otro."},
                    "base_url": {"type": "string"},
                    "username": {"type": "string"},
                    "secret": {"type": "string", "description": "La contraseña, ya obtenida via ask_user_secret."},
                    "database": {"type": "string", "description": "Solo si provider=odoo."},
                    "default_team": {"type": "string", "description": "Solo si provider=odoo, opcional."},
                    "default_stage": {"type": "string", "description": "Solo si provider=odoo, opcional."},
                },
                "required": ["provider", "base_url", "username", "secret"],
            },
        },
    },
]


class SelfConfigAgent(ConfirmableAgent):
    """Auto-configura Vault y CRM via CMDB + Vault + config de Sales reales."""

    tools = _TOOLS
    prompt_key = "pepo.self_config_loop"
    agent_id = "self_config"

    def __init__(self, cfg, *, llm_router=None, cmdb=None, vault=None, local_state=None) -> None:
        super().__init__(cfg, llm_router=llm_router)
        self._cmdb = cmdb
        self._vault = vault
        self._local_state = local_state

    # ── Tools propias ────────────────────────────────────────────────────────

    async def dispatch_tool(self, name: str, args: dict[str, Any]) -> str | ProposalOutcome | None:
        if name == "lookup_cmdb":
            return await self._lookup_cmdb(args.get("query", ""))
        if name == "check_credentials":
            return await self._check_credentials(args.get("device_id", ""))
        if name == "get_crm_config":
            return self._get_crm_config_text()
        if name == "propose_store_credential":
            return ProposalOutcome(kind="store_credential", payload=args)
        if name == "propose_set_crm_config":
            return ProposalOutcome(kind="set_crm_config", payload=args)
        return None

    async def _lookup_cmdb(self, query: str) -> str:
        from nexus.cmdb.lookup import search_devices

        try:
            return await search_devices(self._cmdb, query)
        except Exception:
            logger.exception("Fallo consultando CMDB")
            return "Error consultando el CMDB."

    async def _check_credentials(self, device_id: str) -> str:
        from nexus.vault.check import check_credentials

        return await check_credentials(self._vault, device_id)

    def _get_crm_config_text(self) -> str:
        cfg = self._cfg
        return (
            f"assets_crm: enabled={cfg.assets_crm_enabled}, base_url={cfg.assets_crm_base_url or '-'}, "
            f"username={cfg.assets_crm_username or '-'}, password_set={bool(cfg.assets_crm_password)}\n"
            f"odoo: enabled={cfg.crm_odoo_enabled}, base_url={cfg.crm_odoo_base_url or '-'}, "
            f"database={cfg.crm_odoo_database or '-'}, username={cfg.crm_odoo_username or '-'}, "
            f"password_set={bool(cfg.crm_odoo_password)}"
        )

    # ── Ejecucion tras confirmar ─────────────────────────────────────────────

    async def execute(self, pending: PendingAction) -> dict[str, Any]:
        if pending.kind == "store_credential":
            return await self._execute_store_credential(pending)
        if pending.kind == "set_crm_config":
            return await self._execute_set_crm_config(pending)
        return {"task": pending.task, "is_done": False, "content": None, "error": f"Pendiente desconocido: {pending.kind}"}

    async def _execute_store_credential(self, pending: PendingAction) -> dict[str, Any]:
        payload = pending.payload
        if self._vault is None:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El Vault no esta disponible."}
        if self._vault.is_locked:
            return {"task": pending.task, "is_done": False, "content": None, "error": "El Vault esta bloqueado — desbloquealo desde la pestana Vault e intenta de nuevo."}

        device_id = payload.get("device_id") or ""
        device_name = payload.get("device_name") or device_id or "dispositivo"

        if not device_id:
            if self._cmdb is None:
                return {"task": pending.task, "is_done": False, "content": None, "error": "No hay CMDB disponible para dar de alta el dispositivo."}
            from nexus.cmdb.models import Device

            device_id = f"dev-{uuid.uuid4().hex[:10]}"
            device = Device(
                device_id=device_id,
                name=device_name,
                ip=payload.get("ip") or "",
                type=payload.get("device_type") or "unknown",
                management_protocol=payload.get("management_protocol") or "none",
                discovery_source="pepo_self_config",
            )
            try:
                await self._cmdb.create(device)
            except Exception as exc:
                logger.exception("Fallo dando de alta el dispositivo en el CMDB")
                return {"task": pending.task, "is_done": False, "content": None, "error": f"No pude dar de alta el dispositivo: {exc}"}

        try:
            await self._vault.store(
                device_id=device_id,
                auth_method=payload.get("auth_method", "password"),
                username=payload.get("username", ""),
                secret=payload.get("secret", ""),
                ssh_key=payload.get("ssh_key"),
            )
        except Exception as exc:
            logger.exception("Fallo guardando credenciales en el Vault")
            return {"task": pending.task, "is_done": False, "content": None, "error": f"No pude guardar las credenciales: {exc}"}

        from utils.logger import hito
        hito(
            "pepo.self_config | vault_add_credential | dispositivo=\"{dispositivo}\" | resultado=OK",
            dispositivo=device_name,
        )
        return {
            "task": pending.task, "is_done": True,
            "content": f"Credenciales guardadas en el Vault para '{device_name}' (device_id={device_id}).",
            "error": None,
        }

    async def _execute_set_crm_config(self, pending: PendingAction) -> dict[str, Any]:
        payload = pending.payload
        provider = payload.get("provider", "")
        if provider not in _SUPPORTED_CRM_PROVIDERS:
            return {"task": pending.task, "is_done": False, "content": None, "error": f"Proveedor CRM no soportado: '{provider}'. Hoy solo Assets CRM y Odoo."}
        if self._local_state is None:
            return {"task": pending.task, "is_done": False, "content": None, "error": "No tengo acceso a la configuracion local del escritorio."}

        # Import diferido: evita ciclo de import con products.desktop.backend.settings_routes,
        # que a su vez importa nexus.api.dependencies.auth (donde se construye este agente).
        from products.desktop.backend.settings_routes import _apply_desktop_sales_config

        existing = self._local_state.load_sales_config() or {}
        ex_assets = existing.get("assets_crm", {})
        ex_odoo = existing.get("odoo", {})

        data = {
            "brave": existing.get("brave", {}),
            "google_places": existing.get("google_places", {}),
            "assets_crm": dict(ex_assets),
            "odoo": dict(ex_odoo),
        }
        if provider == "assets_crm":
            data["assets_crm"] = {
                "enabled": True,
                "base_url": payload.get("base_url", ""),
                "username": payload.get("username", ""),
                "password": payload.get("secret") or ex_assets.get("password", ""),
            }
        else:
            data["odoo"] = {
                "enabled": True,
                "base_url": payload.get("base_url", ""),
                "database": payload.get("database", ""),
                "username": payload.get("username", ""),
                "password": payload.get("secret") or ex_odoo.get("password", ""),
                "default_team": payload.get("default_team") or ex_odoo.get("default_team", ""),
                "default_stage": payload.get("default_stage") or ex_odoo.get("default_stage", ""),
            }

        try:
            saved = self._local_state.save_sales_config(data)
            _apply_desktop_sales_config(self._cfg, saved)
        except Exception as exc:
            logger.exception("Fallo guardando la configuracion de CRM")
            return {"task": pending.task, "is_done": False, "content": None, "error": f"No pude guardar la configuracion de CRM: {exc}"}

        from utils.logger import hito
        hito(
            "pepo.self_config | crm_configurar | proveedor=\"{proveedor}\" | resultado=OK",
            proveedor=provider,
        )
        provider_label = "Assets CRM" if provider == "assets_crm" else "Odoo"
        return {
            "task": pending.task, "is_done": True,
            "content": f"Conexion a {provider_label} configurada y activa.",
            "error": None,
        }
