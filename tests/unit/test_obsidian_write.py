"""tests/unit/test_obsidian_write.py

Fase 1 del asistente de Obsidian: escribir notas con vista previa y confirmacion. Se prueba el escritor
seguro (sin LLM), la busqueda de relacionadas, el compositor (con un LLM simulado) y el flujo completo
proponer -> confirmar/cancelar, incluido a traves del coordinador.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from desktop.obsidian.assistant import ObsidianAssistant, folder_hint, split_request
from desktop.obsidian.composer import NoteComposer
from desktop.obsidian.graph import VaultGraph
from desktop.obsidian.related import find_related
from desktop.obsidian.vault import Vault
from desktop.obsidian.writer import (
    Change,
    ChangeError,
    apply_change,
    normalise_tags,
    plan_append,
    plan_new_note,
    render_note,
    safe_folder,
    safe_title,
)
from desktop.storage.obsidian_settings import ObsidianSettingsStore
from nexus.api.schemas.chat import ChatRequest
from nexus.audit.repository import MemoryAuditRepository
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator


def _write(root, rel, text, newline=None):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "Boveda"
    (root / ".obsidian").mkdir(parents=True)
    _write(root, "Redes/Cisco ACI.md", "---\ntags: [redes, cisco]\naliases: [ACI]\n---\nFabric de Cisco con topologia spine leaf y controlador APIC para centros de datos.\n")
    _write(root, "Redes/Spine Leaf.md", "---\ntags: [redes]\n---\nTopologia de dos capas: los spine conectan con todos los leaf.\n")
    _write(root, "Cocina/Receta.md", "Tortilla de patata con cebolla.\n")
    return root


@pytest.fixture
def vault(vault_root) -> Vault:
    return Vault(vault_root)


@pytest.fixture
def graph(vault) -> VaultGraph:
    return VaultGraph.build(vault)


# ── Escritor: nombres, etiquetas, formato ────────────────────────────────────

def test_titles_become_valid_file_names():
    assert safe_title('Redes: "ACI" / v2?') == "Redes ACI v2"
    assert safe_title("  ..  ") == "Nota" and safe_title("CON") == "Nota"
    assert len(safe_title("a" * 300)) <= 100


def test_folders_cannot_escape_or_be_hidden():
    assert safe_folder("../../Windows") == "Windows"
    assert safe_folder(".obsidian/plugins") == "plugins"
    assert safe_folder("Redes\\ACI/") == "Redes/ACI" and safe_folder("") == ""


def test_tags_are_normalised_reusing_the_ones_that_exist():
    assert normalise_tags(["#Redes", "Cisco ACI", "redes", "2026", ""], {"Cisco-ACI"}) == ["redes", "Cisco-ACI"]
    assert len(normalise_tags([f"t{i}" for i in range(20)])) == 5


def test_render_note_has_frontmatter_and_ends_with_one_newline():
    text = render_note("Cuerpo\n\n", ["a", "b"], date(2026, 10, 23), "generada por PEPO (sin verificar)")

    assert text == "---\ncreated: 2026-10-23\ntags: [a, b]\norigen: generada por PEPO (sin verificar)\n---\n\nCuerpo\n"


# ── Escritor: planificar y aplicar ───────────────────────────────────────────

def test_a_new_title_is_created_in_the_requested_folder(vault, graph):
    change = plan_new_note(vault, graph, "Landing zones", "Azure", "texto")

    assert (change.kind, change.path, change.new_text) == ("create", "Azure/Landing zones.md", "texto")


def test_an_existing_title_in_any_folder_becomes_an_append_never_a_second_note(vault, graph):
    change = plan_new_note(vault, graph, "cisco aci", "", "---\ncreated: 2026-10-23\n---\n\nMas informacion.\n")

    assert change.kind == "append" and change.path == "Redes/Cisco ACI.md"
    assert "## Añadido el" in change.added and "Mas informacion." in change.added and "created:" not in change.added


def test_apply_creates_the_file_and_never_overwrites(vault, graph, vault_root):
    change = plan_new_note(vault, graph, "Nueva", "", "contenido\n")

    result = apply_change(vault, change)

    assert result == {"path": "Nueva.md", "kind": "create", "backup": None}
    assert (vault_root / "Nueva.md").read_text(encoding="utf-8") == "contenido\n"
    with pytest.raises(ChangeError, match="ya existe"):
        apply_change(vault, change)
    assert (vault_root / "Nueva.md").read_text(encoding="utf-8") == "contenido\n"


def test_append_backs_up_the_previous_version_and_keeps_the_rest_intact(vault, graph, vault_root):
    original = (vault_root / "Redes/Spine Leaf.md").read_bytes()
    change = plan_append(vault, "Redes/Spine Leaf.md", "Nuevo parrafo.", today=date(2026, 10, 23))

    result = apply_change(vault, change, now=datetime(2026, 10, 23, 12, 0, 0))

    assert (vault_root / result["backup"]).read_bytes() == original
    assert result["backup"] == ".pepo/backups/20261023-120000/Redes/Spine Leaf.md"
    raw = (vault_root / "Redes/Spine Leaf.md").read_bytes()                  # la plantilla usa CRLF y se respeta
    assert raw.startswith(original.rstrip(b"\r\n")) and raw.endswith("## Añadido el 2026-10-23\r\n\r\nNuevo parrafo.\r\n".encode("utf-8"))


def test_append_preserves_windows_line_endings(vault, vault_root):
    _write(vault_root, "Crlf.md", "uno\r\ndos\r\n", newline="")
    change = plan_append(vault, "Crlf.md", "tres", today=date(2026, 10, 23))

    apply_change(vault, change)

    raw = (vault_root / "Crlf.md").read_bytes()
    assert b"\r\n\r\n## " in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_a_note_that_changed_since_the_proposal_is_not_touched(vault, vault_root):
    change = plan_append(vault, "Cocina/Receta.md", "Añadir", today=date(2026, 10, 23))
    (vault_root / "Cocina/Receta.md").write_text("Alguien la edito mientras tanto.\n", encoding="utf-8")

    with pytest.raises(ChangeError, match="ha cambiado"):
        apply_change(vault, change)
    assert (vault_root / "Cocina/Receta.md").read_text(encoding="utf-8") == "Alguien la edito mientras tanto.\n"


@pytest.mark.parametrize("rel", [".obsidian/app.md", ".pepo/x.md", "../fuera.md", "datos.txt", "Credentials.md", "C:/Windows/x.md"])
def test_protected_or_non_markdown_paths_are_refused(vault, rel):
    with pytest.raises(ChangeError):
        apply_change(vault, Change("create", rel, "x"))


def test_unknown_change_kinds_are_refused(vault):
    with pytest.raises(ChangeError, match="desconocido"):
        apply_change(vault, Change("delete", "Receta.md", ""))


# ── Grafo: enlazar texto nuevo ───────────────────────────────────────────────

def test_link_mentions_links_only_the_first_mention_of_existing_notes(graph):
    text, linked = graph.link_mentions("La topologia spine leaf es clave. Repetimos spine leaf. Con ACI y Cisco ACI.")

    # "ACI" (alias de 3 letras) no se enlaza solo: demasiado corto, daria falsos positivos.
    assert text == "La topologia [[Spine Leaf|spine leaf]] es clave. Repetimos spine leaf. Con ACI y [[Cisco ACI]]."
    assert sorted(linked) == ["Redes/Cisco ACI.md", "Redes/Spine Leaf.md"]


def test_link_mentions_skips_code_existing_links_urls_and_ambiguous_names(graph, vault_root):
    text, linked = graph.link_mentions("`spine leaf` y [[Cisco ACI]] y https://x.com/spine leaf\n```\nspine leaf\n```")

    assert linked == [] and text.count("[[") == 1

    _write(vault_root, "Otro/Spine Leaf.md", "otra con el mismo nombre\n")
    ambiguous = VaultGraph.build(Vault(vault_root))
    assert ambiguous.link_mentions("hablamos de spine leaf")[1] == []


def test_link_mentions_can_exclude_the_note_being_extended(graph):
    _, linked = graph.link_mentions("Cisco ACI y spine leaf", exclude={"Redes/Cisco ACI.md"})

    assert linked == ["Redes/Spine Leaf.md"]


def test_sanitize_links_removes_only_the_invented_ones(graph):
    text, removed = graph.sanitize_links("Ver [[Cisco ACI]], [[Inventada]] y [[Otra|con alias]]")

    assert text == "Ver [[Cisco ACI]], Inventada y con alias" and removed == ["Inventada", "Otra"]


# ── Relacionadas ─────────────────────────────────────────────────────────────

def test_related_notes_are_found_by_content_and_unrelated_ones_are_not(graph):
    found = [path for path, _ in find_related(graph, "Quiero apuntar como funciona la topologia spine leaf con APIC")]

    assert found[0] in {"Redes/Cisco ACI.md", "Redes/Spine Leaf.md"} and "Cocina/Receta.md" not in found
    assert find_related(graph, "astronomia agujeros negros") == []
    assert all(p != "Redes/Cisco ACI.md" for p, _ in find_related(graph, "topologia spine leaf APIC", exclude={"Redes/Cisco ACI.md"}))


# ── Compositor (LLM simulado) ────────────────────────────────────────────────

class _FakeRouter:
    """Responde segun el prompt: redactar o contrastar. Guarda lo que recibe."""

    def __init__(self, draft=None, contrast=None, fail=False):
        self.draft, self.contrast, self.fail = draft, contrast, fail
        self.calls: list[dict] = []

    async def call(self, messages, **kwargs):
        system = messages[0]["content"]
        self.calls.append({"system": system, "user": messages[1]["content"]})
        if self.fail:
            return SimpleNamespace(error="boom", content="", tool_calls=None)
        payload = self.draft if "Redactas UNA nota" in system else self.contrast
        return SimpleNamespace(error=None, content=json.dumps(payload) if payload is not None else "esto no es json", tool_calls=None)


@pytest.mark.asyncio
async def test_draft_returns_title_body_and_tags_and_none_when_unusable():
    ok = NoteComposer(_FakeRouter(draft={"title": "T", "body": "B", "tags": ["a"]}))
    draft = await ok.draft("peticion", "", ["X"], [])
    assert (draft.title, draft.body, draft.tags) == ("T", "B", ["a"])

    assert await NoteComposer(_FakeRouter(draft=None)).draft("p", "", [], []) is None             # no es JSON
    assert await NoteComposer(_FakeRouter(draft={"title": "T", "body": ""})).draft("p", "", [], []) is None
    assert await NoteComposer(_FakeRouter(fail=True)).draft("p", "", [], []) is None


@pytest.mark.asyncio
async def test_secrets_are_redacted_before_reaching_the_llm():
    router = _FakeRouter(draft={"title": "T", "body": "B"})

    await NoteComposer(router).draft("guarda esto", "mi password: hunter2hunter2 y el token sk-abcdefghijklmnop1234", [], [])

    sent = router.calls[0]["user"]
    assert "hunter2hunter2" not in sent and "sk-abcdefghijklmnop1234" not in sent


@pytest.mark.asyncio
async def test_contrast_keeps_only_findings_about_notes_it_was_given(graph):
    router = _FakeRouter(contrast={
        "duplicates": [{"nota": "cisco aci", "motivo": "ya explica la fabric"}, {"nota": "Inventada", "motivo": "x"}],
        "contradictions": [{"nota": "Spine Leaf", "motivo": "dice tres capas y la existente dos"}, {"nota": "Spine Leaf", "motivo": ""}],
    })
    related = [graph.notes["Redes/Cisco ACI.md"], graph.notes["Redes/Spine Leaf.md"]]

    result = await NoteComposer(router).contrast("Nueva", "cuerpo", related)

    assert result.duplicates == [("Cisco ACI", "ya explica la fabric")]
    assert result.contradictions == [("Spine Leaf", "dice tres capas y la existente dos")] and result.has_findings


@pytest.mark.asyncio
async def test_contrast_without_related_notes_does_not_call_the_llm_and_degrades_gracefully(graph):
    router = _FakeRouter(contrast={"duplicates": [], "contradictions": []})

    assert (await NoteComposer(router).contrast("N", "c", [])).has_findings is False and router.calls == []
    unavailable = await NoteComposer(_FakeRouter(fail=True)).contrast("N", "c", [graph.notes["Redes/Cisco ACI.md"]])
    assert unavailable.available is False and not unavailable.has_findings


# ── Peticion ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, has_content", [
    ("apunta en Obsidian una nota sobre las landing zones de Azure", False),
    ("apunta en Obsidian: reunión con Laura el jueves a las 10, revisar presupuesto de red", True),
    ("anota en Obsidian que mañana tengo que llamar a Laura por el presupuesto", True),
    ("crea una nota de PTP\nProtocolo de precisión de tiempo que sincroniza relojes en redes Ethernet", True),
])
def test_dictated_content_is_separated_from_the_request(message, has_content):
    request, content = split_request(message)

    assert bool(content) is has_content and request


def test_the_folder_the_user_names_is_used_if_it_exists_or_created_if_not(graph):
    assert folder_hint("apunta una nota en la carpeta redes sobre PTP", graph) == "Redes"
    assert folder_hint("apunta una nota en la carpeta Azure nueva sobre PTP", graph) == "Azure nueva"
    assert folder_hint("apunta una nota sobre PTP", graph) == ""
    assert folder_hint("en la carpeta ../../Windows", graph) == ""            # una ruta rara no se interpreta: raiz
    assert folder_hint("en la carpeta Windows/System32 sobre algo", graph) == "Windows/System32"


# ── Flujo completo ───────────────────────────────────────────────────────────

class _MemStore:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def save(self, *, agent_id, context_id, kind, payload):
        self.rows[(agent_id, context_id)] = payload

    def delete(self, *, agent_id, context_id):
        self.rows.pop((agent_id, context_id), None)

    def list_for_agent(self, agent_id):
        return [SimpleNamespace(context_id=c, payload=p) for (a, c), p in self.rows.items() if a == agent_id]


def _assistant(tmp_path, vault_root, router, store=None) -> ObsidianAssistant:
    settings = ObsidianSettingsStore(tmp_path / "s.json", detect=lambda: vault_root)
    return ObsidianAssistant(settings, llm_router=router, store=store, today=lambda: date(2026, 10, 23))


GENERATED = {"title": "Landing zones de Azure", "body": "Una landing zone prepara la suscripcion. Se apoya en la topologia spine leaf de red.", "tags": ["Azure", "Redes"]}


@pytest.mark.asyncio
async def test_a_proposal_shows_a_preview_and_writes_nothing_until_confirmed(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root, _FakeRouter(draft=GENERATED, contrast={"duplicates": [], "contradictions": []}))

    text = await assistant.handle("apunta en Obsidian una nota sobre las landing zones de Azure", "ctx")

    assert "**Propuesta: crear la nota** `Landing zones de Azure.md`" in text
    assert "Etiquetas: azure, redes" in text and "[[Spine Leaf]]" in text and "Origen: generada por PEPO (sin verificar)" in text
    assert "¿La escribo? Responde **sí** o **no**." in text
    assert not (vault_root / "Landing zones de Azure.md").exists() and assistant.has_pending("ctx")


@pytest.mark.asyncio
async def test_confirming_writes_the_note_with_frontmatter_validated_links_and_provenance(tmp_path, vault_root):
    router = _FakeRouter(
        draft={**GENERATED, "body": "Se apoya en [[Cisco ACI]] y en [[Inventada]] y en la topologia spine leaf."},
        contrast={"duplicates": [], "contradictions": []},
    )
    assistant = _assistant(tmp_path, vault_root, router)
    await assistant.handle("apunta en Obsidian una nota sobre las landing zones de Azure", "ctx")

    reply = await assistant.confirm("ctx")

    written = (vault_root / "Landing zones de Azure.md").read_text(encoding="utf-8")
    assert "`Landing zones de Azure.md`" in reply
    assert written.startswith("---\ncreated: 2026-10-23\ntags: [azure, redes]\norigen: generada por PEPO (sin verificar)\n---\n")
    assert "> [!warning] Nota generada por PEPO" in written
    assert "[[Cisco ACI]]" in written and "[[Inventada]]" not in written and "Inventada" in written
    assert "[[Spine Leaf|spine leaf]]" in written
    assert not assistant.has_pending("ctx")


@pytest.mark.asyncio
async def test_dictated_content_is_marked_as_the_users_and_not_flagged_as_unverified(tmp_path, vault_root):
    router = _FakeRouter(draft={"title": "Reunion con Laura", "body": "- Jueves 10:00\n- Revisar presupuesto", "tags": ["reunion"]},
                         contrast={"duplicates": [], "contradictions": []})
    assistant = _assistant(tmp_path, vault_root, router)

    text = await assistant.handle("apunta en Obsidian: reunión con Laura el jueves a las 10, revisar presupuesto de red", "c")
    await assistant.confirm("c")

    note = (vault_root / "Reunion con Laura.md").read_text(encoding="utf-8")
    assert "Origen: apuntada por el usuario, con formato de PEPO" in text and "origen: apuntada por el usuario" in note and "[!warning]" not in note
    assert "CONTENIDO DEL USUARIO:\nreunión con Laura" in router.calls[0]["user"] or "reunión con Laura" in router.calls[0]["user"]


@pytest.mark.asyncio
async def test_contrast_findings_are_shown_before_asking_for_confirmation(tmp_path, vault_root):
    router = _FakeRouter(draft={"title": "Fabric ACI", "body": "ACI usa spine leaf y APIC.", "tags": []}, contrast={
        "duplicates": [{"nota": "Cisco ACI", "motivo": "ya describe la fabric con APIC"}],
        "contradictions": [{"nota": "Spine Leaf", "motivo": "dice tres capas, la existente dos"}],
    })

    text = await _assistant(tmp_path, vault_root, router).handle("apunta una nota sobre la fabric ACI con APIC y spine leaf", "c")

    assert "**Contraste con tu bóveda**" in text
    assert "Posible duplicado de [[Cisco ACI]]: ya describe la fabric con APIC" in text
    assert "Posible contradicción con [[Spine Leaf]]: dice tres capas, la existente dos" in text
    assert text.index("Contraste con tu bóveda") < text.index("¿La escribo?")


@pytest.mark.asyncio
async def test_an_existing_title_proposes_appending_and_confirming_keeps_a_backup(tmp_path, vault_root):
    router = _FakeRouter(draft={"title": "Spine Leaf", "body": "Detalle nuevo sobre ECMP.", "tags": []},
                         contrast={"duplicates": [], "contradictions": []})
    assistant = _assistant(tmp_path, vault_root, router)
    original = (vault_root / "Redes/Spine Leaf.md").read_bytes()

    text = await assistant.handle("apunta una nota sobre spine leaf y ECMP", "c")
    reply = await assistant.confirm("c")

    assert "añadir al final de la nota existente** `Redes/Spine Leaf.md`" in text and "no creo otra" in text
    assert not (vault_root / "Spine Leaf.md").exists()
    assert "Detalle nuevo sobre ECMP." in (vault_root / "Redes/Spine Leaf.md").read_text(encoding="utf-8")
    backup = next((vault_root / ".pepo/backups").rglob("Spine Leaf.md"))
    assert backup.read_bytes() == original and "Antes copié la versión anterior" in reply


@pytest.mark.asyncio
async def test_cancelling_discards_the_proposal_and_writes_nothing(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root, _FakeRouter(draft=GENERATED, contrast={"duplicates": [], "contradictions": []}))
    await assistant.handle("apunta en Obsidian una nota sobre landing zones", "c")

    assistant.cancel("c")

    assert not assistant.has_pending("c") and not (vault_root / "Landing zones de Azure.md").exists()
    assert "No había nada pendiente" in await assistant.confirm("c")


@pytest.mark.asyncio
async def test_a_failing_llm_leaves_no_proposal(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root, _FakeRouter(fail=True))

    text = await assistant.handle("apunta en Obsidian una nota sobre redes", "c")

    assert "No he conseguido que el modelo redacte" in text and not assistant.has_pending("c")


@pytest.mark.asyncio
async def test_if_the_llm_cannot_contrast_the_user_is_told(tmp_path, vault_root):
    router = _FakeRouter(draft={"title": "Fabric ACI", "body": "ACI usa spine leaf y APIC.", "tags": []}, contrast=None)

    text = await _assistant(tmp_path, vault_root, router).handle("apunta una nota sobre la fabric ACI con APIC y spine leaf", "c")

    assert "No he podido contrastarla con tus notas" in text


@pytest.mark.asyncio
async def test_confirming_after_the_target_changed_reports_it_and_writes_nothing(tmp_path, vault_root):
    router = _FakeRouter(draft={"title": "Spine Leaf", "body": "Detalle.", "tags": []}, contrast={"duplicates": [], "contradictions": []})
    assistant = _assistant(tmp_path, vault_root, router)
    await assistant.handle("apunta una nota sobre spine leaf", "c")
    (vault_root / "Redes/Spine Leaf.md").write_text("cambiada\n", encoding="utf-8")

    reply = await assistant.confirm("c")

    assert "No he escrito nada" in reply and "ha cambiado" in reply
    assert (vault_root / "Redes/Spine Leaf.md").read_text(encoding="utf-8") == "cambiada\n"


@pytest.mark.asyncio
async def test_a_pending_proposal_survives_a_restart(tmp_path, vault_root):
    store = _MemStore()
    first = _assistant(tmp_path, vault_root, _FakeRouter(draft=GENERATED, contrast={"duplicates": [], "contradictions": []}), store)
    await first.handle("apunta en Obsidian una nota sobre landing zones", "c")

    second = _assistant(tmp_path, vault_root, None, store)
    second.load_pending_from_store()
    assert second.has_pending("c") and (await second.list_pending())[0]["summary"].startswith("Crear «Landing zones de Azure»")
    await second.confirm("c")

    assert (vault_root / "Landing zones de Azure.md").exists() and store.rows == {}


@pytest.mark.asyncio
async def test_the_proposal_is_not_built_inside_protected_places(tmp_path, vault_root):
    router = _FakeRouter(draft={"title": "Credentials", "body": "x", "tags": []}, contrast={"duplicates": [], "contradictions": []})

    text = await _assistant(tmp_path, vault_root, router).handle("apunta una nota sobre claves", "c")

    assert "No puedo crear esa nota" in text and not (vault_root / "Credentials.md").exists()


# ── A traves del coordinador ─────────────────────────────────────────────────

def _coordinator(assistant) -> NexusCoordinator:
    return NexusCoordinator(
        alertmanager=None, grafana=None, prometheus=None,
        incident_repository=MemoryIncidentRepository(), audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(), obsidian_assistant=assistant,
    )


def _chat(message):
    return ChatRequest(message=message, mode="general", context_id="ctx", user_id="u")


@pytest.mark.asyncio
async def test_through_the_chat_a_yes_writes_the_note(tmp_path, vault_root):
    coordinator = _coordinator(_assistant(tmp_path, vault_root, _FakeRouter(draft=GENERATED, contrast={"duplicates": [], "contradictions": []})))

    proposal = await coordinator.handle_chat(_chat("apunta en Obsidian una nota sobre las landing zones de Azure"))
    assert proposal.agent == "obsidian-assistant" and "¿La escribo?" in proposal.response
    assert not (vault_root / "Landing zones de Azure.md").exists()

    done = await coordinator.handle_chat(_chat("sí"))

    assert "he creado `Landing zones de Azure.md`" in done.response and (vault_root / "Landing zones de Azure.md").exists()


@pytest.mark.asyncio
async def test_through_the_chat_a_no_or_a_change_of_topic_writes_nothing(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root, _FakeRouter(draft=GENERATED, contrast={"duplicates": [], "contradictions": []}))
    coordinator = _coordinator(assistant)

    await coordinator.handle_chat(_chat("apunta en Obsidian una nota sobre las landing zones de Azure"))
    refused = await coordinator.handle_chat(_chat("no"))
    assert refused.response == "Vale, no escribo nada." and not assistant.has_pending("ctx")

    await coordinator.handle_chat(_chat("apunta en Obsidian una nota sobre las landing zones de Azure"))
    await coordinator.handle_chat(_chat("repasa mi bóveda de Obsidian"))              # otro tema: la propuesta se descarta
    assert not assistant.has_pending("ctx") and not (vault_root / "Landing zones de Azure.md").exists()


@pytest.mark.asyncio
async def test_pending_notes_can_be_listed_confirmed_and_cancelled_from_the_agent_manager(tmp_path, vault_root):
    assistant = _assistant(tmp_path, vault_root, _FakeRouter(draft=GENERATED, contrast={"duplicates": [], "contradictions": []}))
    coordinator = _coordinator(assistant)
    await coordinator.handle_chat(_chat("apunta en Obsidian una nota sobre las landing zones de Azure"))

    listed = await coordinator.list_pending_actions()
    assert [p["agent_id"] for p in listed] == ["obsidian"]

    result = await coordinator.confirm_pending_action("ctx")
    assert result["status"] == "ok" and (vault_root / "Landing zones de Azure.md").exists()

    await coordinator.handle_chat(_chat("apunta en Obsidian una nota sobre las landing zones de Azure"))
    assert (await coordinator.cancel_pending_action("ctx"))["status"] == "ok" and not assistant.has_pending("ctx")

