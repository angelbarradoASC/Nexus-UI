"""tests/unit/test_self_config_agent.py

Tests unitarios para SelfConfigAgent — auto-configuracion de Vault y CRM
por chat, con confirmacion en dos pasos (propose -> confirm).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from desktop.local_agents.self_config_agent import SelfConfigAgent


class _FakeLLMResponse:
    def __init__(self, *, tool_calls=None, content=None, error=None):
        self.tool_calls = tool_calls
        self.content = content
        self.error = error


def _tool_call(call_id: str, name: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


class _FakeLLMRouter:
    def __init__(self, responses: list[_FakeLLMResponse]):
        self._responses = list(responses)

    async def call(self, **kwargs):
        return self._responses.pop(0)


class _FakeCMDB:
    def __init__(self, existing: list | None = None):
        self._existing = existing or []
        self.created: list = []

    async def list_devices(self, enabled_only: bool = True):
        return list(self._existing)

    async def create(self, device):
        self.created.append(device)
        return device


class _FakeVault:
    def __init__(self, *, is_locked: bool = False):
        self.is_locked = is_locked
        self.stored: list[dict] = []

    async def store(self, *, device_id, auth_method, username, secret, ssh_key=None):
        self.stored.append({
            "device_id": device_id, "auth_method": auth_method,
            "username": username, "secret": secret, "ssh_key": ssh_key,
        })
        return SimpleNamespace(cred_id="cred-test", device_id=device_id)

    async def get_credential(self, device_id):
        return None


def _fake_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        assets_crm_enabled=False, assets_crm_base_url="", assets_crm_username="", assets_crm_password="",
        crm_odoo_enabled=False, crm_odoo_base_url="", crm_odoo_database="", crm_odoo_username="",
        crm_odoo_password="", crm_odoo_default_team="", crm_odoo_default_stage="",
        brave_search_enabled=False, brave_search_api_key="", brave_search_rate_limit=1.0,
        google_places_enabled=False, google_places_api_key="", google_places_rate_limit=0.5,
        google_places_max_results_per_query=20,
    )


def _local_state(tmp_path):
    from desktop.config import DesktopSettings
    from desktop.storage.local_state import DesktopLocalState

    return DesktopLocalState(DesktopSettings(local_data_root=str(tmp_path)))


# ── Vault: dar de alta un dispositivo nuevo + guardar credenciales ─────────────

@pytest.mark.asyncio
async def test_propose_store_credential_for_new_device_creates_pending():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "lookup_cmdb", query="BeaServer")]),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "propose_store_credential",
            device_name="BeaServer", ip="10.0.0.5", device_type="server",
            management_protocol="ssh", auth_method="password", username="admin", secret="s3cr3t",
        )]),
    ])
    cmdb = _FakeCMDB(existing=[])
    vault = _FakeVault()
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=cmdb, vault=vault, local_state=None)

    result = await agent.propose("ctx-1", "añade BeaServer al vault, usuario admin, contraseña s3cr3t")

    assert result["kind"] == "store_credential"
    assert result["payload"]["device_name"] == "BeaServer"
    assert agent.has_pending("ctx-1") is True
    assert vault.stored == []
    assert cmdb.created == []


@pytest.mark.asyncio
async def test_confirm_store_credential_creates_device_and_stores_vault_entry():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "lookup_cmdb", query="BeaServer")]),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "propose_store_credential",
            device_name="BeaServer", ip="10.0.0.5", device_type="server",
            management_protocol="ssh", auth_method="password", username="admin", secret="s3cr3t",
        )]),
    ])
    cmdb = _FakeCMDB(existing=[])
    vault = _FakeVault()
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=cmdb, vault=vault, local_state=None)
    await agent.propose("ctx-1", "añade BeaServer al vault")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is True
    assert result["error"] is None
    assert len(cmdb.created) == 1
    assert cmdb.created[0].name == "BeaServer"
    assert cmdb.created[0].ip == "10.0.0.5"
    assert len(vault.stored) == 1
    assert vault.stored[0]["username"] == "admin"
    assert vault.stored[0]["secret"] == "s3cr3t"
    assert vault.stored[0]["device_id"] == cmdb.created[0].device_id
    assert agent.has_pending("ctx-1") is False


@pytest.mark.asyncio
async def test_confirm_store_credential_fails_when_vault_locked():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "lookup_cmdb", query="BeaServer")]),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "propose_store_credential",
            device_name="BeaServer", auth_method="password", username="admin", secret="s3cr3t",
        )]),
    ])
    cmdb = _FakeCMDB(existing=[])
    vault = _FakeVault(is_locked=True)
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=cmdb, vault=vault, local_state=None)
    await agent.propose("ctx-1", "añade BeaServer al vault")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is False
    assert result["error"]
    assert vault.stored == []
    assert cmdb.created == []


@pytest.mark.asyncio
async def test_ask_user_secret_roundtrip_carries_secret_to_proposal():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "ask_user_secret", question="¿Cual es la contraseña?")]),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "propose_store_credential",
            device_id="dev-existing", device_name="BeaServer",
            auth_method="password", username="admin", secret="s3cr3t",
        )]),
    ])
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=None)

    proposal = await agent.propose("ctx-1", "añade credenciales para BeaServer")
    assert proposal["kind"] == "ask_user_secret"
    assert agent.pending_kind("ctx-1") == "ask_user_secret"

    result = await agent.confirm("ctx-1", "s3cr3t")

    assert result["next_kind"] == "store_credential"
    assert result["next_payload"]["secret"] == "s3cr3t"
    assert agent.pending_kind("ctx-1") == "store_credential"


@pytest.mark.asyncio
async def test_ask_user_about_password_is_redacted_even_when_llm_used_wrong_tool():
    """El LLM no siempre respeta la instruccion de usar ask_user_secret para
    contraseñas — probado en verificacion manual. La deteccion por texto de
    la pregunta debe marcarlo como ask_user_secret de todos modos."""
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call("c1", "ask_user", question="¿Cual es la contraseña del servidor?")]),
    ])
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=None)

    result = await agent.propose("ctx-1", "añade credenciales para BeaServer")

    assert result["kind"] == "ask_user_secret"
    assert agent.pending_kind("ctx-1") == "ask_user_secret"


@pytest.mark.asyncio
async def test_freeform_question_without_tool_call_is_treated_as_ask_user_secret():
    """El modelo a veces no llama a ninguna tool y responde una pregunta en
    texto libre — probado en verificacion manual con el modelo real. Debe
    tratarse como ask_user (con deteccion de secreto), no como finish, o se
    pierde el estado pendiente."""
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=None, content="Por favor, ingresa la contraseña para el servidor 10.0.0.99:"),
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c2", "propose_store_credential",
            device_id="dev-existing", device_name="10.0.0.99",
            auth_method="password", username="admin", secret="s3cr3t",
        )]),
    ])
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=None)

    proposal = await agent.propose("ctx-1", "añade el servidor 10.0.0.99 al vault, usuario admin")
    assert proposal["kind"] == "ask_user_secret"
    assert agent.has_pending("ctx-1") is True

    result = await agent.confirm("ctx-1", "s3cr3t")

    assert result["next_kind"] == "store_credential"
    assert result["next_payload"]["secret"] == "s3cr3t"


@pytest.mark.asyncio
async def test_freeform_final_answer_without_question_mark_still_finishes():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=None, content="No encuentro ningun proveedor CRM llamado asi, hoy solo soporto Assets CRM y Odoo."),
    ])
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=None)

    result = await agent.propose("ctx-1", "conecta a HubSpot")

    assert result["kind"] == "finish"
    assert agent.has_pending("ctx-1") is False


# ── CRM: configurar Assets CRM / Odoo ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_and_confirm_set_crm_config_persists_and_applies_to_cfg(tmp_path):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_set_crm_config",
            provider="odoo", base_url="https://odoo.local", username="admin",
            secret="odoop4ss", database="nexus",
        )]),
    ])
    cfg = _fake_cfg()
    local_state = _local_state(tmp_path)
    agent = SelfConfigAgent(cfg, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=local_state)

    proposal = await agent.propose("ctx-1", "conecta esto a mi CRM Odoo")
    assert proposal["kind"] == "set_crm_config"
    assert proposal["payload"]["provider"] == "odoo"

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is True
    saved = local_state.load_sales_config()
    assert saved["odoo"]["base_url"] == "https://odoo.local"
    assert saved["odoo"]["database"] == "nexus"
    assert cfg.crm_odoo_enabled is True
    assert cfg.crm_odoo_password == "odoop4ss"
    assert cfg.crm_odoo_base_url == "https://odoo.local"


@pytest.mark.asyncio
async def test_set_crm_config_preserves_other_provider(tmp_path):
    local_state = _local_state(tmp_path)
    local_state.save_sales_config({
        "brave": {}, "google_places": {},
        "assets_crm": {"enabled": True, "base_url": "https://assets.local", "username": "assets_user", "password": "assets_pw"},
        "odoo": {},
    })
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_set_crm_config",
            provider="odoo", base_url="https://odoo.local", username="admin", secret="odoop4ss",
        )]),
    ])
    cfg = _fake_cfg()
    agent = SelfConfigAgent(cfg, llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=local_state)
    await agent.propose("ctx-1", "conecta a Odoo")

    await agent.confirm("ctx-1")

    saved = local_state.load_sales_config()
    assert saved["assets_crm"]["base_url"] == "https://assets.local"
    assert saved["assets_crm"]["password"] == "assets_pw"
    assert saved["odoo"]["base_url"] == "https://odoo.local"


@pytest.mark.asyncio
async def test_unsupported_crm_provider_returns_error_without_writing(tmp_path):
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_set_crm_config",
            provider="hubspot", base_url="https://hubspot.local", username="admin", secret="x",
        )]),
    ])
    local_state = _local_state(tmp_path)
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=_FakeCMDB(), vault=_FakeVault(), local_state=local_state)
    await agent.propose("ctx-1", "conecta a HubSpot")

    result = await agent.confirm("ctx-1")

    assert result["is_done"] is False
    assert "no soportado" in result["error"].lower() or "hubspot" in result["error"].lower()
    assert local_state.load_sales_config() is None


# ── Cancelacion ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_clears_pending_without_writing():
    llm = _FakeLLMRouter([
        _FakeLLMResponse(tool_calls=[_tool_call(
            "c1", "propose_store_credential",
            device_name="BeaServer", auth_method="password", username="admin", secret="s3cr3t",
        )]),
    ])
    cmdb = _FakeCMDB()
    vault = _FakeVault()
    agent = SelfConfigAgent(_fake_cfg(), llm_router=llm, cmdb=cmdb, vault=vault, local_state=None)
    await agent.propose("ctx-1", "añade BeaServer al vault")

    agent.cancel("ctx-1")

    assert agent.has_pending("ctx-1") is False
    assert vault.stored == []
    assert cmdb.created == []
