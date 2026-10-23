"""
desktop/obsidian/assistant.py
--------------------------------
Punto de entrada del chat de PEPO para la boveda de Obsidian (docs/PLAN_PEPO_OBSIDIAN.md).

- "repasa mi boveda" -> informe determinista (audit.py). Sin LLM.
- "apunta en Obsidian ..." -> PROPUESTA de nota con vista previa; solo se escribe cuando el usuario confirma.
  Reparto de trabajo: el LLM redacta el cuerpo y contrasta con las notas parecidas; el CODIGO busca las
  relacionadas, pone los enlaces (solo a notas que existen), da el formato, valida la ruta y escribe.
- Enlazar/ordenar notas YA existentes llega en la fase 2: se dice con claridad, no se finge.

Reglas: nunca borra ni sobrescribe; la boveda sale de los ajustes (nunca del mensaje); lo que viaja al LLM
va con `redact()`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import date
from typing import Any

from desktop.code_agent.workspace import WorkspaceError

from .audit import AuditReport, audit_graph, format_report
from .composer import Contrast, NoteComposer
from .graph import VaultGraph
from .related import find_related
from .vault import Vault
from .writer import Change, ChangeError, apply_change, normalise_tags, plan_new_note, render_note, safe_folder, safe_title

logger = logging.getLogger("nexus.obsidian")

_PERSISTENCE_KEY = "obsidian"

_AUDIT = re.compile(r"\b(repasa|repasar|repaso|revisa|revisar|audita|auditar|analiza|analizar|estado|que hay|como esta|enlaces rotos|resumen)\b")
_MODIFY = re.compile(r"\b(enlaza|enlazar|ordena|ordenar|organiza|organizar|formato|formatea|limpia|arregla|mueve|etiqueta)\b")
_WRITE = re.compile(r"\b(apunta|apuntar|anota|anotar|escribe|escribir|crea|crear|guarda|guardar|añade|anade|redacta|redactar)\b")
_WRITE_TARGET = re.compile(r"\b(nota|notas|apunte|idea|resumen de|apunta|apuntar|anota|anotar)\b")
_DICTATION = re.compile(r"\b(?:apunta|anota|apuntar|anotar|guarda|escribe)\b.{0,60}?\bque\s+(.{15,})$", re.DOTALL)
_FOLDER = re.compile(r"\bcarpeta\s+[\"«']?([^\"»'\n,.:;]{2,60})", re.IGNORECASE)

PREVIEW_CHARS = 1_800
STRONG_RELATED_SCORE = 1.5
TITLES_FOR_DRAFT = 150


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def classify_intent(message: str) -> str:
    """'audit' | 'modify' | 'write' | 'unknown'. Heuristico y barato."""
    text = _plain(message)
    if _WRITE.search(text) and _WRITE_TARGET.search(text):
        return "write"
    if _MODIFY.search(text):
        return "modify"
    if _AUDIT.search(text):
        return "audit"
    return "unknown"


def split_request(message: str) -> tuple[str, str]:
    """(peticion, contenido_del_usuario). Si el usuario DICTA el contenido (tras un salto de linea, tras ':' o con
    'anota que ...') el LLM solo le da formato; si solo pide un tema, la nota es GENERADA y se marca como tal."""
    text = message.strip()
    if "\n" in text:
        first, rest = text.split("\n", 1)
        if len(rest.strip()) >= 20:
            return first.strip(), rest.strip()
    colon = re.match(r"^(.{5,160}?):\s+(.{40,})$", text, re.DOTALL)
    if colon:
        return colon.group(1).strip(), colon.group(2).strip()
    dictated = _DICTATION.search(_plain(text))
    if dictated:
        return text, text[len(text) - len(dictated.group(1)):].strip()
    return text, ""


def folder_hint(message: str, graph: VaultGraph) -> str:
    """Carpeta que el usuario nombra ('en la carpeta Redes'), o '' para la raiz. Si existe, se usa tal cual."""
    match = _FOLDER.search(message)
    if not match:
        return ""
    wanted = safe_folder(match.group(1))
    if not wanted:
        return ""
    folders = {str(p.rsplit("/", 1)[0]) for p in graph.notes if "/" in p}
    # Una carpeta que ya existe gana aunque el usuario siga escribiendo ("en la carpeta Redes sobre PTP").
    for folder in sorted(folders, key=len, reverse=True):
        if wanted.lower() == folder.lower() or wanted.lower().startswith(folder.lower() + " "):
            return folder
    # Carpeta nueva: el nombre acaba donde empieza el tema ("... Azure nueva sobre PTP" -> "Azure nueva").
    cut = re.split(r"\s+(?:sobre|acerca|para|con|que|donde|llamada|titulada|de)\s+", wanted, maxsplit=1, flags=re.IGNORECASE)[0]
    return safe_folder(cut)


_NOT_YET_MODIFY = (
    "\n\n---\nEsto es lo que cambiaría para enlazar y ordenar, pero todavía no modifico notas que ya existen: "
    "llegará en la siguiente fase, con vista previa y tu confirmación."
)


class ObsidianAssistant:
    def __init__(self, settings: Any, llm_router: Any = None, store: Any = None, *, today=date.today) -> None:
        self._settings = settings
        self._composer = NoteComposer(llm_router) if llm_router is not None else None
        self._store = store
        self._today = today
        self._pending: dict[str, dict[str, Any]] = {}

    # ── Boveda ───────────────────────────────────────────────────────────────

    def open_vault(self) -> Vault | str:
        """La boveda autorizada, o un mensaje (str) apto para el usuario si no se puede usar."""
        if not self._settings.enabled:
            return "El asistente de Obsidian está desactivado en Configuración."
        path, _ = self._settings.effective_vault()
        if path is None:
            return (
                "No encuentro ninguna bóveda de Obsidian. Abre una en Obsidian o indícame la carpeta en "
                "Configuración › Obsidian."
            )
        try:
            return Vault(path)
        except WorkspaceError as exc:
            return str(exc)

    @staticmethod
    def build_report(vault: Vault) -> AuditReport:
        graph = VaultGraph.build(vault)
        return audit_graph(graph, vault.root.name, vault.skipped_protected)

    # ── Pendientes (confirmacion en dos pasos) ───────────────────────────────

    def load_pending_from_store(self) -> None:
        if self._store is None:
            return
        for row in self._store.list_for_agent(_PERSISTENCE_KEY):
            self._pending[row.context_id] = dict(row.payload)

    def has_pending(self, context_id: str) -> bool:
        return context_id in self._pending

    async def list_pending(self) -> list[dict[str, Any]]:
        return [
            {"context_id": cid, "agent_id": "obsidian", "kind": "note_change", "summary": data.get("summary", "Cambio en la bóveda")}
            for cid, data in self._pending.items()
        ]

    def cancel(self, context_id: str) -> None:
        self._pending.pop(context_id, None)
        if self._store is not None:
            self._store.delete(agent_id=_PERSISTENCE_KEY, context_id=context_id)

    async def confirm(self, context_id: str, user_reply: str | None = None) -> str:
        """Escribe el cambio pendiente. Devuelve el mensaje para el usuario."""
        data = self._pending.get(context_id)
        if data is None:
            return "No había nada pendiente de confirmar."
        self.cancel(context_id)
        vault = self.open_vault()
        if isinstance(vault, str):
            return vault
        change = Change.from_dict(data["change"])
        try:
            result = await asyncio.to_thread(apply_change, vault, change)
        except ChangeError as exc:
            return f"No he escrito nada: {exc}"
        except OSError as exc:
            logger.exception("Obsidian: fallo escribiendo en la boveda")
            return f"No he podido escribir en la bóveda: {exc}"
        if result["kind"] == "create":
            return f"Hecho: he creado `{result['path']}`. Ya la tienes en Obsidian."
        return (
            f"Hecho: he añadido el texto al final de `{result['path']}`. "
            f"Antes copié la versión anterior en `{result['backup']}` por si quieres volver atrás."
        )

    def _save_pending(self, context_id: str, change: Change, summary: str) -> None:
        self._pending[context_id] = {"change": change.to_dict(), "summary": summary}
        if self._store is not None:
            self._store.save(agent_id=_PERSISTENCE_KEY, context_id=context_id, kind="note_change", payload=self._pending[context_id])

    # ── Chat ─────────────────────────────────────────────────────────────────

    async def handle(self, message: str, context_id: str = "default") -> str:
        vault = self.open_vault()
        if isinstance(vault, str):
            return vault
        intent = classify_intent(message)
        if intent == "write":
            return await self._propose_note(vault, context_id, message)
        report = await asyncio.to_thread(self.build_report, vault)
        text = format_report(report)
        if intent == "modify":
            text += _NOT_YET_MODIFY
        return text

    async def _propose_note(self, vault: Vault, context_id: str, message: str) -> str:
        if self._composer is None:
            return "No tengo un modelo de lenguaje disponible ahora mismo para redactar la nota. Inténtalo de nuevo en un momento."
        graph = await asyncio.to_thread(VaultGraph.build, vault)
        request, content = split_request(message)

        # Orden de los titulos que ve el LLM: primero los parecidos a la peticion.
        related_for_draft = [path for path, _ in find_related(graph, message, k=8)]
        titles = [graph.notes[p].title for p in related_for_draft] + [
            n.title for p, n in sorted(graph.notes.items()) if p not in related_for_draft
        ]
        existing_tags = sorted({t for n in graph.notes.values() for t in n.tags})
        draft = await self._composer.draft(request, content, titles[:TITLES_FOR_DRAFT], existing_tags)
        if draft is None:
            return "No he conseguido que el modelo redacte la nota. No he escrito nada; prueba de nuevo o dame más detalle."

        title = safe_title(draft.title or request[:60])
        same_title = next((p for p, n in graph.notes.items() if n.title.lower() == title.lower()), None)

        # El CODIGO enlaza: primero se quita cualquier enlace inventado, luego se enlazan las menciones reales.
        body, _ = graph.sanitize_links(draft.body)
        body, linked = graph.link_mentions(body, exclude={same_title} if same_title else None)
        related = [(p, s) for p, s in find_related(graph, f"{title}\n{draft.body}", k=3, exclude={same_title} if same_title else None)]
        # La seccion "Notas relacionadas" escribe enlaces sin pasar por el LLM: solo las claramente parecidas.
        strong = [p for p, s in related if s >= max(STRONG_RELATED_SCORE, 0.4 * related[0][1])]
        extra = [p for p in strong if p not in linked]
        if extra:
            body += "\n\n## Notas relacionadas\n" + "\n".join(f"- [[{graph.notes[p].title}]]" for p in extra)
            linked = linked + extra

        generated = not content.strip()
        origin = "generada por PEPO (sin verificar)" if generated else "apuntada por el usuario, con formato de PEPO"
        if generated:
            body = "> [!warning] Nota generada por PEPO a partir de su conocimiento general. Contrasta los datos antes de fiarte.\n\n" + body
        tags = normalise_tags(draft.tags, set(existing_tags))
        text = render_note(body, tags, self._today(), origin)

        folder = folder_hint(message, graph)
        try:
            change = plan_new_note(vault, graph, title, folder, text)
        except ChangeError as exc:
            return f"No puedo crear esa nota: {exc}"

        contrast = await self._composer.contrast(title, draft.body, [graph.notes[p] for p, _ in related])
        self._save_pending(context_id, change, f"{'Crear' if change.kind == 'create' else 'Añadir a'} «{title}»")
        return self._format_proposal(change, graph, tags, linked, generated, contrast, bool(related))

    @staticmethod
    def _format_proposal(change: Change, graph: VaultGraph, tags: list[str], linked: list[str], generated: bool,
                         contrast: Contrast, had_related: bool) -> str:
        if change.kind == "create":
            lines = [f"**Propuesta: crear la nota** `{change.path}`"]
        else:
            lines = [f"**Propuesta: añadir al final de la nota existente** `{change.path}` (ya tienes una con ese título; no creo otra)"]
        details = []
        if tags:
            details.append("Etiquetas: " + ", ".join(tags))
        if linked:
            details.append("Enlaces: " + ", ".join(f"[[{graph.notes[p].title}]]" for p in linked))
        details.append("Origen: " + ("generada por PEPO, sin verificar" if generated else "tu texto, con formato"))
        lines.append(" · ".join(details))

        if contrast.has_findings:
            lines.append("\n**Contraste con tu bóveda**")
            lines += [f"- Posible duplicado de [[{t}]]: {why}" for t, why in contrast.duplicates]
            lines += [f"- Posible contradicción con [[{t}]]: {why}" for t, why in contrast.contradictions]
        elif not contrast.available:
            lines.append("\nNo he podido contrastarla con tus notas (el modelo no respondió); revísala tú.")
        elif had_related:
            lines.append("\nContraste con tus notas parecidas: sin duplicados ni contradicciones.")

        preview = (change.added if change.kind == "append" else change.new_text).strip()
        if len(preview) > PREVIEW_CHARS:
            preview = preview[:PREVIEW_CHARS].rsplit("\n", 1)[0] + "\n[… recortado en la vista previa]"
        lines.append("\n---\n" + preview + "\n---")
        lines.append("¿La escribo? Responde **sí** o **no**.")
        return "\n".join(lines)
