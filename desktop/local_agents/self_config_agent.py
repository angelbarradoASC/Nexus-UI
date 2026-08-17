"""
desktop/local_agents/self_config_agent.py
--------------------------------------------
SelfConfigAgent — permite a PEPO auto-configurar integraciones reales por
chat: dar de alta credenciales en el Vault (opcionalmente dando de alta el
dispositivo en el CMDB si es nuevo) y configurar la conexion a un CRM
(Assets u Odoo, los dos que Sales ya soporta).

Mismo patron que RemoteOpsAgent: bucle generico de tool-calling, el LLM
decide que herramienta llamar, y nada se escribe hasta que el usuario
confirma explicitamente en el siguiente mensaje. El determinismo viene del
toolbox + bucle, no de codigo distinto por integracion — para lo que no esta
soportado (un proveedor de CRM que no sea assets_crm/odoo, por ejemplo) se
responde con honestidad, no se inventa.

Seguridad: los secretos (contraseñas, tokens, claves) se piden SIEMPRE via
la tool `ask_user_secret`, nunca `ask_user` — el backend usa esa distincion
para marcar la respuesta y evitar que quede en texto plano en el historial
de conversaciones persistido (ver ChatResponse.redact_next_reply). El
secreto en si sigue viajando en claro hasta el Vault/config (igual que ya
pasa hoy con el formulario de la pestaña Vault); lo unico que cambia es que
no queda legible sin limite de tiempo en pepo_conversations.db.

El LLM no siempre respeta esa distincion de herramienta (probado: a veces
usa ask_user para pedir la contraseña pese a la instruccion del prompt). Por
eso _store_outcome() aplica ademas una deteccion heuristica sobre el TEXTO
de la pregunta — belt and suspenders, la redaccion no depende solo de que
el modelo elija bien la tool.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nexus.self_config_agent")

_MAX_LOOP_STEPS = 6

_SECRET_QUESTION_PATTERN = re.compile(
    r"contrase|password|\btoken\b|clave|secreto|\bsecret\b|api[\s_-]?key",
    re.IGNORECASE,
)

# Heuristica para reconocer que una respuesta en texto libre (sin tool call)
# le esta pidiendo un dato al usuario en vez de dar una respuesta final.
# Probado con el modelo real: no siempre termina en "?" — a veces es una
# orden imperativa terminada en ":" ("...ingresa la contraseña:").
_FOLLOWUP_QUESTION_PATTERN = re.compile(
    r"[?:]\s*$|^(por favor|necesito|podr[ií]as|ind[ií]came|dime|cu[aá]l es|introduce|ingresa|proporciona|facilita)",
    re.IGNORECASE,
)

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
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pregunta al usuario UN dato NO sensible que falte (nombre, IP, tipo...). "
                "Nunca uses esto para contraseñas, tokens o claves — para eso usa ask_user_secret."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user_secret",
            "description": (
                "Identica a ask_user, pero UNICAMENTE para datos sensibles (contraseña, "
                "token, clave). Marca la respuesta para que no quede en texto plano en "
                "el historial de conversaciones."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Termina: ya se ha respondido con lo que sabes (incluye 'proveedor no "
                "soportado' o 'dispositivo no encontrado' como respuestas finales validas, "
                "no como fallos)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]

_ASK_KINDS = {"ask_user", "ask_user_secret"}
_PROPOSAL_KINDS = {"store_credential", "set_crm_config"}


@dataclass(slots=True)
class PendingSelfConfig:
    task: str
    kind: str  # "ask_user" | "ask_user_secret" | "store_credential" | "set_crm_config"
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class SelfConfigAgent:
    """Auto-configura Vault y CRM via CMDB + Vault + config de Sales reales."""

    def __init__(self, cfg, *, llm_router=None, cmdb=None, vault=None, local_state=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._cmdb = cmdb
        self._vault = vault
        self._local_state = local_state
        self._pending: dict[str, PendingSelfConfig] = {}

    # ── Tool: lookup_cmdb ────────────────────────────────────────────────────

    async def _lookup_cmdb(self, query: str) -> str:
        from nexus.cmdb.lookup import search_devices

        try:
            return await search_devices(self._cmdb, query)
        except Exception:
            logger.exception("Fallo consultando CMDB")
            return "Error consultando el CMDB."

    # ── Tool: check_credentials ──────────────────────────────────────────────

    async def _check_credentials(self, device_id: str) -> str:
        from nexus.vault.check import check_credentials

        return await check_credentials(self._vault, device_id)

    # ── Tool: get_crm_config ─────────────────────────────────────────────────

    def _get_crm_config_text(self) -> str:
        cfg = self._cfg
        return (
            f"assets_crm: enabled={cfg.assets_crm_enabled}, base_url={cfg.assets_crm_base_url or '-'}, "
            f"username={cfg.assets_crm_username or '-'}, password_set={bool(cfg.assets_crm_password)}\n"
            f"odoo: enabled={cfg.crm_odoo_enabled}, base_url={cfg.crm_odoo_base_url or '-'}, "
            f"database={cfg.crm_odoo_database or '-'}, username={cfg.crm_odoo_username or '-'}, "
            f"password_set={bool(cfg.crm_odoo_password)}"
        )

    # ── Bucle generico ───────────────────────────────────────────────────────

    async def _run_loop(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        from nexus.prompts import resolve_prompt_sync

        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": resolve_prompt_sync("pepo.self_config_loop")}, *messages]

        for _ in range(_MAX_LOOP_STEPS):
            try:
                response = await self._llm_router.call(
                    messages=messages,
                    tools=_TOOLS,
                    tool_choice="auto",
                    preferred_level=2,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=30.0,
                )
            except Exception as exc:
                logger.exception("Fallo en el bucle de auto-configuracion")
                return {"kind": "finish", "summary": f"No pude continuar: {exc}"}

            if response.error:
                return {"kind": "finish", "summary": f"No pude continuar: {response.error}"}

            if not response.tool_calls:
                # El modelo no siempre respeta el protocolo de tool-calling —
                # a veces responde una pregunta de seguimiento en texto libre
                # en vez de llamar a ask_user/ask_user_secret (probado en
                # verificacion manual). Si el texto termina en "?", se trata
                # como un ask_user implicito (sin tool_call_id real) en vez
                # de darlo por terminado — si no, se pierde el estado
                # pendiente Y la deteccion de secreto de _store_outcome.
                content = response.content or ""
                stripped = content.strip()
                if stripped and _FOLLOWUP_QUESTION_PATTERN.search(stripped):
                    messages.append({"role": "assistant", "content": content})
                    return {"kind": "ask_user", "question": stripped, "messages": messages, "tool_call_id": None}
                return {"kind": "finish", "summary": content or "Hecho."}

            call = response.tool_calls[0]
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            messages.append({
                "role": "assistant",
                "content": response.content or None,
                "tool_calls": response.tool_calls,
            })
            for extra_call in response.tool_calls[1:]:
                messages.append({
                    "role": "tool", "tool_call_id": extra_call.get("id", ""),
                    "content": "Ignorada — ya se proceso otra herramienta en este turno.",
                })

            if name == "lookup_cmdb":
                result_text = await self._lookup_cmdb(args.get("query", ""))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
                continue

            if name == "check_credentials":
                result_text = await self._check_credentials(args.get("device_id", ""))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
                continue

            if name == "get_crm_config":
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": self._get_crm_config_text()})
                continue

            if name == "propose_store_credential":
                return {"kind": "store_credential", "payload": args, "messages": messages, "tool_call_id": call.get("id", "")}

            if name == "propose_set_crm_config":
                return {"kind": "set_crm_config", "payload": args, "messages": messages, "tool_call_id": call.get("id", "")}

            if name in _ASK_KINDS:
                return {"kind": name, "question": args.get("question", "?"), "messages": messages, "tool_call_id": call.get("id", "")}

            if name == "finish":
                return {"kind": "finish", "summary": args.get("summary", "Hecho.")}

            return {"kind": "finish", "summary": f"Herramienta desconocida: {name}"}

        return {"kind": "finish", "summary": "No he podido resolverlo en los pasos disponibles."}

    def _store_outcome(self, context_id: str, task: str, outcome: dict[str, Any]) -> dict[str, Any]:
        kind = outcome["kind"]

        # Red de seguridad determinista: si el LLM pidio un dato via ask_user
        # (no ask_user_secret) pero el TEXTO de la pregunta suena a secreto,
        # se trata igualmente como ask_user_secret para la redaccion en el
        # historial — no depende solo de que el modelo eligiera bien la tool.
        if kind == "ask_user" and _SECRET_QUESTION_PATTERN.search(outcome.get("question", "")):
            kind = "ask_user_secret"

        if kind in _ASK_KINDS:
            self._pending[context_id] = PendingSelfConfig(
                task=task, kind=kind, messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
            )
            return {"kind": kind, "task": task, "question": outcome["question"]}

        if kind in _PROPOSAL_KINDS:
            self._pending[context_id] = PendingSelfConfig(
                task=task, kind=kind, messages=outcome["messages"], tool_call_id=outcome["tool_call_id"],
                payload=outcome["payload"],
            )
            return {"kind": kind, "task": task, "payload": outcome["payload"]}

        return {"kind": "finish", "task": task, "summary": outcome.get("summary", "Hecho.")}

    # ── API publica ──────────────────────────────────────────────────────────

    async def propose(self, context_id: str, task: str, *, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        if self._llm_router is None:
            return {"kind": "finish", "task": task, "summary": "El razonamiento por LLM no esta disponible ahora mismo."}
        seed_messages = [*(history or []), {"role": "user", "content": task}]
        outcome = await self._run_loop(seed_messages)
        return self._store_outcome(context_id, task, outcome)

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    async def list_pending(self) -> list[dict[str, Any]]:
        """Solo lectura, para el gestor de agentes — nunca expone secretos.

        Async por consistencia con el resto de agentes (ver mouse_agent.py)."""
        return [
            {
                "context_id": context_id,
                "agent_id": "self_config",
                "kind": pending.kind,
                "summary": pending.task,
            }
            for context_id, pending in self._pending.items()
        ]

    def pending_kind(self, context_id: str) -> str | None:
        pending = self._pending.get(context_id)
        return pending.kind if pending else None

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)

    # ── Ejecucion tras confirmar ─────────────────────────────────────────────

    async def _execute_store_credential(self, pending: PendingSelfConfig) -> dict[str, Any]:
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

    async def _execute_set_crm_config(self, pending: PendingSelfConfig) -> dict[str, Any]:
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

    async def confirm(self, context_id: str, user_reply: str | None = None) -> dict[str, Any] | None:
        """Continua/ejecuta lo pendiente. `user_reply` es obligatorio si el pendiente es 'ask_user'/'ask_user_secret'."""
        pending = self._pending.pop(context_id, None)
        if pending is None:
            return None

        if pending.kind == "store_credential":
            return await self._execute_store_credential(pending)

        if pending.kind == "set_crm_config":
            return await self._execute_set_crm_config(pending)

        if pending.kind in _ASK_KINDS:
            if pending.tool_call_id:
                pending.messages.append({
                    "role": "tool", "tool_call_id": pending.tool_call_id, "content": user_reply or "",
                })
            else:
                # Pregunta en texto libre (sin tool call real detras) — ver
                # el branch "no tool_calls" de _run_loop. No hay tool_call_id
                # al que responder, asi que la respuesta entra como turno de
                # usuario normal.
                pending.messages.append({"role": "user", "content": user_reply or ""})
            outcome = await self._run_loop(pending.messages)
            stored = self._store_outcome(context_id, pending.task, outcome)
            if stored["kind"] == "finish":
                return {"task": pending.task, "is_done": True, "content": stored["summary"], "error": None}
            if stored["kind"] in _ASK_KINDS:
                return {
                    "task": pending.task, "is_done": False, "content": None, "error": None,
                    "next_kind": stored["kind"], "next_question": stored["question"],
                }
            if stored["kind"] in _PROPOSAL_KINDS:
                return {
                    "task": pending.task, "is_done": False, "content": None, "error": None,
                    "next_kind": stored["kind"], "next_payload": stored["payload"],
                }

        return None
