"""tests/unit/test_obsidian_assistant.py

Cableado del asistente de Obsidian (fase 0, solo lectura): ajustes, intencion, enrutado desde el chat y
rutas de la API. El nucleo (analisis, grafo, auditoria) esta en test_obsidian_core.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desktop.code_agent.workspace import WorkspaceError
from desktop.obsidian.assistant import ObsidianAssistant, classify_intent
from desktop.runtime.skill_router import DesktopSkillRouter
from desktop.storage.obsidian_settings import ObsidianSettingsStore
from nexus.api.schemas.chat import ChatRequest
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator
from products.desktop.backend import obsidian_routes


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Boveda"
    (root / ".obsidian").mkdir(parents=True)
    (root / "A.md").write_text("---\ntags: [x]\n---\nVer [[No existe]].\n", encoding="utf-8")
    (root / "Vacia.md").write_text("", encoding="utf-8")
    return root


def _store(tmp_path, detected=None) -> ObsidianSettingsStore:
    return ObsidianSettingsStore(tmp_path / "obsidian_settings.json", detect=lambda: detected)


# ── Ajustes ──────────────────────────────────────────────────────────────────

def test_without_settings_the_vault_open_in_obsidian_is_used(tmp_path, vault_root):
    store = _store(tmp_path, detected=vault_root)

    assert store.enabled and store.effective_vault() == (vault_root, "detected")


def test_a_configured_vault_wins_and_must_contain_the_obsidian_folder(tmp_path, vault_root):
    store = _store(tmp_path, detected=None)
    plain = tmp_path / "carpeta"
    plain.mkdir()

    with pytest.raises(WorkspaceError, match="no parece una boveda"):
        store.set_vault(str(plain))
    store.set_vault(str(vault_root))

    assert store.effective_vault() == (vault_root, "configured")
    store.set_vault("")                                                       # vuelve a la detectada
    assert store.effective_vault() == (None, "none")


def test_a_configured_vault_that_disappears_falls_back_to_the_detected_one(tmp_path, vault_root):
    other = tmp_path / "Otra"
    (other / ".obsidian").mkdir(parents=True)
    store = _store(tmp_path, detected=other)
    store.set_vault(str(vault_root))
    (vault_root / ".obsidian").rmdir()

    assert store.effective_vault() == (other, "detected")


# ── Intencion ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("repasa mi bóveda de Obsidian", "audit"),
    ("¿qué hay roto en mis notas?", "audit"),
    ("revisa los enlaces rotos de mi bóveda", "audit"),
    ("enlaza mis notas entre sí", "modify"),
    ("ordena mi bóveda y dale formato", "modify"),
    ("apunta en Obsidian una nota sobre las landing zones", "write"),
    ("anota esto en Obsidian: reunión el jueves", "write"),
    ("crea una nota sobre PTP", "write"),
])
def test_intent_is_classified_from_the_message(message, expected):
    assert classify_intent(message) == expected


# ── Asistente ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_audit_request_returns_the_report(tmp_path, vault_root):
    assistant = ObsidianAssistant(_store(tmp_path, detected=vault_root))

    text = await assistant.handle("repasa mi bóveda")

    assert "Repaso de la bóveda «Boveda»" in text and "[[No existe]]" in text and "Notas vacías" in text
    assert "todavía no modifico" not in text


@pytest.mark.asyncio
async def test_writing_without_an_llm_says_so_and_touches_nothing(tmp_path, vault_root):
    assistant = ObsidianAssistant(_store(tmp_path, detected=vault_root))          # sin router
    before = sorted(p.name for p in vault_root.iterdir())

    text = await assistant.handle("apunta en Obsidian una nota sobre redes")

    assert "No tengo un modelo de lenguaje" in text
    assert sorted(p.name for p in vault_root.iterdir()) == before and not assistant.has_pending("default")


@pytest.mark.asyncio
async def test_a_maintenance_request_on_a_vault_with_nothing_to_do_says_so(tmp_path, vault_root):
    text = await ObsidianAssistant(_store(tmp_path, detected=vault_root)).handle("enlaza mis notas")

    assert "no hay nada que cambiar" in text


@pytest.mark.asyncio
async def test_no_vault_or_disabled_gives_a_clear_message(tmp_path, vault_root):
    assert "No encuentro ninguna bóveda" in await ObsidianAssistant(_store(tmp_path)).handle("repasa mi bóveda")
    store = _store(tmp_path, detected=vault_root)
    store.set_enabled(False)
    assert "desactivado" in await ObsidianAssistant(store).handle("repasa mi bóveda")


# ── Enrutado desde el chat ───────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "repasa mi bóveda de Obsidian",
    "apunta en obsidian una nota sobre azure",
    "enlaza mis notas",
    "ordena mi bóveda",
])
def test_the_skill_router_sends_vault_requests_to_the_obsidian_skill(message):
    resolution = DesktopSkillRouter().resolve(message)

    assert resolution.skill_id == "notes.obsidian" and resolution.required_capabilities == ["obsidian.vault"]


@pytest.mark.parametrize("message", [
    "guarda la contraseña de este servidor en el vault",
    "crea un ticket de la alerta del servidor",
    "hablame de las notas de la reunion",
    "revisa el servidor linux, la cpu va lenta",
])
def test_unrelated_requests_do_not_reach_the_obsidian_skill(message):
    assert DesktopSkillRouter().resolve(message).skill_id != "notes.obsidian"


@pytest.mark.asyncio
async def test_the_coordinator_answers_vault_requests_without_touching_the_llm(tmp_path, vault_root):
    coordinator = NexusCoordinator(
        alertmanager=None, grafana=None, prometheus=None,
        incident_repository=MemoryIncidentRepository(), audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(), obsidian_assistant=ObsidianAssistant(_store(tmp_path, detected=vault_root)),
    )

    response = await coordinator.handle_chat(ChatRequest(message="repasa mi bóveda de Obsidian", mode="general", context_id="c"))

    assert response.agent == "obsidian-assistant" and response.status == "accepted"
    assert "Repaso de la bóveda" in response.response


@pytest.mark.asyncio
async def test_a_failure_reading_the_vault_is_reported_not_raised(tmp_path):
    class _Broken:
        def has_pending(self, context_id):
            return False

        async def handle(self, message, context_id="default"):
            raise RuntimeError("disco desconectado")

    coordinator = NexusCoordinator(
        alertmanager=None, grafana=None, prometheus=None,
        incident_repository=MemoryIncidentRepository(), audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(), obsidian_assistant=_Broken(),
    )

    response = await coordinator.handle_chat(ChatRequest(message="repasa mi bóveda de Obsidian", mode="general", context_id="c"))

    assert response.status == "degraded" and "No he podido leer tu bóveda" in response.response


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, vault_root):
    app = FastAPI()
    app.include_router(obsidian_routes.router)
    store = _store(tmp_path, detected=vault_root)
    app.dependency_overrides[obsidian_routes.get_obsidian_settings_store] = lambda: store
    return TestClient(app)


def test_api_settings_audit_and_vault_validation(client, tmp_path, vault_root):
    settings = client.get("/api/desktop/obsidian/settings").json()
    assert settings["enabled"] and settings["vault"]["name"] == "Boveda" and settings["vault"]["source"] == "detected"

    audit = client.get("/api/desktop/obsidian/audit").json()
    assert audit["counts"]["notes"] == 2 and audit["counts"]["broken"] == 1 and audit["counts"]["empty"] == 1

    bad = client.put("/api/desktop/obsidian/vault", json={"path": str(tmp_path)})
    assert bad.status_code == 422 and "no parece una boveda" in bad.json()["detail"]

    assert client.put("/api/desktop/obsidian/vault", json={"path": str(vault_root)}).json()["vault"]["source"] == "configured"
    assert client.put("/api/desktop/obsidian/enabled", json={"enabled": False}).json()["enabled"] is False
    assert client.get("/api/desktop/obsidian/audit").status_code == 409
