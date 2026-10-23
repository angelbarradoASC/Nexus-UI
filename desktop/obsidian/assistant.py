"""
desktop/obsidian/assistant.py
--------------------------------
Punto de entrada del chat de PEPO para la boveda de Obsidian (docs/PLAN_PEPO_OBSIDIAN.md).

- "repasa mi boveda" -> informe determinista (audit.py). Sin LLM.
- "apunta en Obsidian ..." -> PROPUESTA de nota con vista previa. El LLM redacta y contrasta con las notas
  parecidas (y, si la nota es generada, con resultados web); el CODIGO busca relacionadas, enlaza, da formato y escribe.
- "enlaza / arregla / da formato / etiqueta / ordena / actualiza el indice" -> PROPUESTA por lotes sobre las notas
  que ya existen (maintain.py), con diff. Casi todo determinista; el LLM solo sugiere etiquetas.

Reglas: NUNCA escribe sin confirmacion (si/no); nunca borra ni sobrescribe; antes de modificar una nota guarda
una copia; la boveda sale de los ajustes (nunca del mensaje); lo que viaja al LLM va con `redact()`.
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
from .composer import Contrast, NoteComposer, WebCheck
from .graph import VaultGraph
from .maintain import OPS, Plan, build_plan, describe_change, find_index_note, find_target
from .related import find_related
from .vault import Vault
from .writer import (
    BatchResult,
    Change,
    ChangeError,
    apply_batch,
    normalise_tags,
    plan_new_note,
    render_note,
    safe_folder,
    safe_title,
)

logger = logging.getLogger("nexus.obsidian")

_PERSISTENCE_KEY = "obsidian"

_AUDIT = re.compile(r"\b(repasa|repasar|repaso|revisa|revisar|audita|auditar|analiza|analizar|estado|que hay|como esta|enlaces rotos|resumen)\b")
_WRITE = re.compile(r"\b(apunta|apuntar|anota|anotar|escribe|escribir|crea|crear|guarda|guardar|añade|anade|redacta|redactar)\b")
_WRITE_TARGET = re.compile(r"\b(nota|notas|apunte|idea|resumen de|apunta|apuntar|anota|anotar)\b")
_DICTATION = re.compile(r"\b(?:apunta|anota|apuntar|anotar|guarda|escribe)\b.{0,60}?\bque\s+(.{15,})$", re.DOTALL)
_FOLDER = re.compile(r"\bcarpeta\s+[\"«']?([^\"»'\n,.:;]{2,60})", re.IGNORECASE)

_OP_PATTERNS: dict[str, re.Pattern[str]] = {
    "link": re.compile(r"\b(enlaza\w*|enlazar\w*|conecta\w*|relaciona\w*|interconecta\w*)\b"),
    "fix": re.compile(r"\b(arregla\w*|repara\w*|corrige\w*|soluciona\w*)\b"),
    "format": re.compile(r"\b(formato|formatea\w*|limpia\w*|normaliza\w*)\b"),
    "tags": re.compile(r"\b(etiqueta\w*|etiquetar\w*|tags)\b"),
    "index": re.compile(r"\b(indice|mapa de notas|moc)\b"),
    "order": re.compile(r"\b(ordena\w*|ordenar\w*|organiza\w*|mueve\w*|carpetas)\b"),
}
_ALL = re.compile(r"\b(manten\w*|mantenimiento|pon en orden|deja\w* ordenad\w*|ordena todo|todo ordenado)\b")

PREVIEW_CHARS = 1_800
BATCH_PREVIEW_CHARS = 3_200
BATCH_EXAMPLES = 4
MAX_PENDING_BYTES = 5_000_000
TITLES_FOR_DRAFT = 150


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def maintenance_ops(message: str) -> set[str]:
    """Que operaciones de mantenimiento pide el mensaje (vacio si ninguna). 'arregla' arregla enlaces y formato;
    'mantén/pon en orden' las pide todas."""
    text = _plain(message)
    if _ALL.search(text):
        return set(OPS)
    ops = {op for op, pattern in _OP_PATTERNS.items() if pattern.search(text)}
    if "fix" in ops and "format" not in ops and not re.search(r"enlaces?\b", text):
        ops.add("format")                    # "arregla mi boveda" = enlaces rotos + formato
    return ops


def classify_intent(message: str) -> str:
    """'write' | 'modify' | 'audit' | 'unknown'. 'modify' = mantenimiento de notas existentes."""
    text = _plain(message)
    if _WRITE.search(text) and _WRITE_TARGET.search(text):
        return "write"
    if maintenance_ops(message):
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


_SEARCH_STOP = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y", "e", "o", "u", "en", "con", "sin", "por", "para",
    "su", "sus", "se", "que", "como", "sobre", "entre", "a", "es", "son", "lo", "le", "les", "mi", "mis", "tu", "tus",
})


def search_queries(title: str) -> list[str]:
    """Consultas para contrastar una nota en internet, de mas a menos especifica. Un titulo entero ('Landing Zones y su
    relacion con la topologia Spine Leaf') no devuelve nada en los buscadores (medido el 2026-10-23): se prueba con
    sus palabras clave (hasta 6) y, si tampoco hay resultados, con las 3 primeras."""
    words = [w for w in re.findall(r"[\w'+#.-]+", title, flags=re.UNICODE) if w.lower() not in _SEARCH_STOP and len(w) > 1]
    queries = [" ".join(words[:6])]
    if len(words) > 3:
        queries.append(" ".join(words[:3]))
    return [q for q in dict.fromkeys(queries) if q] or [title]


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


class ObsidianAssistant:
    def __init__(
        self, settings: Any, llm_router: Any = None, store: Any = None, *, today=date.today, web_search: Any = None,
    ) -> None:
        self._settings = settings
        self._composer = NoteComposer(llm_router) if llm_router is not None else None
        self._store = store
        self._today = today
        self._web_search = web_search                  # async (consulta) -> [{title, url, description}] o None
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

    def _save_pending(self, context_id: str, changes: list[Change], summary: str) -> None:
        self._pending[context_id] = {"changes": [c.to_dict() for c in changes], "summary": summary}
        if self._store is not None:
            self._store.save(agent_id=_PERSISTENCE_KEY, context_id=context_id, kind="note_change", payload=self._pending[context_id])

    async def confirm(self, context_id: str, user_reply: str | None = None) -> str:
        """Escribe los cambios pendientes. Devuelve el mensaje para el usuario."""
        data = self._pending.get(context_id)
        if data is None:
            return "No había nada pendiente de confirmar."
        self.cancel(context_id)
        vault = self.open_vault()
        if isinstance(vault, str):
            return vault
        raw_changes = data.get("changes") or ([data["change"]] if data.get("change") else [])
        changes = [Change.from_dict(item) for item in raw_changes]
        try:
            result = await asyncio.to_thread(apply_batch, vault, changes)
        except Exception:
            logger.exception("Obsidian: fallo escribiendo en la boveda")
            return "No he podido escribir en la bóveda (error del sistema de ficheros). No se ha aplicado nada más."
        return self._format_result(changes, result)

    @staticmethod
    def _format_result(changes: list[Change], result: BatchResult) -> str:
        if len(changes) == 1:
            if result.failed:
                return f"No he escrito nada: {result.failed[0][1]}"
            done = result.applied[0]
            if done["kind"] == "create":
                return f"Hecho: he creado `{done['path']}`. Ya la tienes en Obsidian."
            if done["kind"] == "move":
                return f"Hecho: he movido `{done['from']}` a `{done['path']}`."
            verb = "añadido el texto al final de" if done["kind"] == "append" else "actualizado"
            return (
                f"Hecho: he {verb} `{done['path']}`. "
                f"Antes copié la versión anterior en `{done['backup']}` por si quieres volver atrás."
            )
        kinds = [item["kind"] for item in result.applied]
        parts = [f"{kinds.count(k)} {label}" for k, label in (("replace", "modificadas"), ("append", "ampliadas"), ("create", "creadas"), ("move", "movidas")) if kinds.count(k)]
        lines = [f"Hecho: {len(result.applied)} cambios aplicados ({', '.join(parts) or 'ninguno'})."]
        backups = sorted({item["backup"].rsplit("/", 1)[0] for item in result.applied if item.get("backup")})
        if backups:
            lines.append(f"Las versiones anteriores están en `{backups[0]}/` por si quieres volver atrás.")
        if result.failed:
            lines.append(f"No he podido aplicar {len(result.failed)}:")
            lines += [f"- `{path}`: {why}" for path, why in result.failed[:6]]
        return "\n".join(lines)

    # ── Chat ─────────────────────────────────────────────────────────────────

    async def handle(self, message: str, context_id: str = "default") -> str:
        vault = self.open_vault()
        if isinstance(vault, str):
            return vault
        intent = classify_intent(message)
        if intent == "write":
            return await self._propose_note(vault, context_id, message)
        if intent == "modify":
            return await self._propose_maintenance(vault, context_id, message, maintenance_ops(message))
        report = await asyncio.to_thread(self.build_report, vault)
        return format_report(report)

    # ── Mantenimiento de notas existentes ────────────────────────────────────

    async def _propose_maintenance(self, vault: Vault, context_id: str, message: str, ops: set[str]) -> str:
        if "tags" in ops and self._composer is None:
            ops = ops - {"tags"}
        graph = await asyncio.to_thread(VaultGraph.build, vault)
        if not graph.notes:
            return "Tu bóveda no tiene notas todavía: no hay nada que enlazar ni ordenar."
        target = find_target(message, graph)
        plan = await build_plan(vault, graph, ops, target=target, composer=self._composer, today=self._today())
        if plan.empty:
            lines = ["He revisado " + (f"`{target}`" if target else "tu bóveda") + " y no hay nada que cambiar con lo que me has pedido."]
            if plan.skipped:
                lines += ["", "Lo que he dejado sin tocar:"] + [f"- {item}" for item in plan.skipped[:8]]
            return "\n".join(lines)
        if sum(len(c.new_text) for c in plan.changes) > MAX_PENDING_BYTES:
            return "Son demasiados cambios de golpe. Pídemelo por partes (una nota, o una operación cada vez)."
        summary = f"Mantenimiento de la bóveda: {len(plan.changes)} cambios"
        self._save_pending(context_id, plan.changes, summary)
        return self._format_batch(plan, target)

    @staticmethod
    def _format_batch(plan: Plan, target: str | None) -> str:
        scope = f"la nota `{target}`" if target else "tu bóveda"
        lines = [f"**Propuesta de mantenimiento de {scope}** ({len(plan.changes)} cambios)"]
        lines += [f"- {item}" for item in plan.summary]
        edits = [c for c in plan.changes if c.kind in {"replace", "append"}]
        others = [c for c in plan.changes if c.kind not in {"replace", "append"}]
        lines.append(f"Notas a modificar: {len(edits)} · a crear: {sum(c.kind == 'create' for c in others)} · a mover: {sum(c.kind == 'move' for c in others)}")
        budget = BATCH_PREVIEW_CHARS
        shown = 0
        for change in [*edits[:BATCH_EXAMPLES], *others[:BATCH_EXAMPLES]]:
            piece = describe_change(change, limit=min(700, budget))
            if change.kind in {"replace", "append"}:
                block = f"\n`{change.path}`\n````diff\n{piece}\n````"
            else:
                block = f"\n- {piece}"
            if budget - len(block) < 0 and shown:
                break
            budget -= len(block)
            shown += 1
            lines.append(block)
        if len(plan.changes) > shown:
            lines.append(f"\n… y {len(plan.changes) - shown} cambios más del mismo tipo.")
        if plan.skipped:
            lines += ["", "Lo que dejo sin tocar:"] + [f"- {item}" for item in plan.skipped[:6]]
        lines.append("\nAntes de modificar cada nota guardo una copia en `.pepo/backups`. ¿Lo aplico? Responde **sí** o **no**.")
        return "\n".join(lines)

    # ── Notas nuevas ─────────────────────────────────────────────────────────

    async def _propose_note(self, vault: Vault, context_id: str, message: str) -> str:
        if self._composer is None:
            return "No tengo un modelo de lenguaje disponible ahora mismo para redactar la nota. Inténtalo de nuevo en un momento."
        graph = await asyncio.to_thread(VaultGraph.build, vault)
        request, content = split_request(message)
        self._composer.rate_limited = False

        # El indice lista TODAS las notas: parecido a todo y util para nada. Ni se ofrece ni se enlaza como relacionada.
        index_path = find_index_note(graph)
        skip = {index_path} if index_path else set()

        # Orden de los titulos que ve el LLM: primero los parecidos a la peticion.
        related_for_draft = [path for path, _ in find_related(graph, message, k=8, exclude=skip)]
        titles = [graph.notes[p].title for p in related_for_draft] + [
            n.title for p, n in sorted(graph.notes.items()) if p not in related_for_draft and p not in skip
        ]
        existing_tags = sorted({t for n in graph.notes.values() for t in n.tags})
        draft = await self._composer.draft(request, content, titles[:TITLES_FOR_DRAFT], existing_tags)
        if draft is None:
            return "No he conseguido que el modelo redacte la nota. No he escrito nada; prueba de nuevo o dame más detalle."

        title = safe_title(draft.title or request[:60])
        same_title = next((p for p, n in graph.notes.items() if n.title.lower() == title.lower()), None)
        exclude = ({same_title} if same_title else set()) | skip

        # El CODIGO enlaza: primero se quita cualquier enlace inventado, luego se enlazan las menciones reales.
        body, _ = graph.sanitize_links(draft.body)
        body, linked = graph.link_mentions(body, exclude=exclude)
        related = find_related(graph, f"{title}\n{draft.body}", k=3, exclude=exclude)

        # El LLM contrasta con las notas parecidas y DECIDE cuales son del mismo tema; el TF-IDF solo propone candidatas
        # (en una boveda pequeña casaba "Cisco ACI" con una nota de Azure por palabras sueltas). Sin contraste no se
        # añade la seccion "Notas relacionadas": mejor ningun enlace que uno dudoso.
        contrast = await self._composer.contrast(title, draft.body, [graph.notes[p] for p, _ in related])
        by_title = {graph.notes[p].title: p for p, _ in related}
        extra = [by_title[t] for t in contrast.related if t in by_title and by_title[t] not in linked]
        if extra:
            body += "\n\n## Notas relacionadas\n" + "\n".join(f"- [[{graph.notes[p].title}]]" for p in extra)
            linked = linked + extra

        generated = not content.strip()
        web = await self._web_check(title, draft.body) if generated else None
        if generated:
            body, origin = self._provenance(body, web)
        else:
            origin = "apuntada por el usuario, con formato de PEPO"
        tags = normalise_tags(draft.tags, set(existing_tags))
        text = render_note(body, tags, self._today(), origin)

        folder = folder_hint(message, graph)
        try:
            change = plan_new_note(vault, graph, title, folder, text)
        except ChangeError as exc:
            return f"No puedo crear esa nota: {exc}"

        self._save_pending(context_id, [change], f"{'Crear' if change.kind == 'create' else 'Añadir a'} «{title}»")
        reason = (
            "el proveedor de IA ha limitado el uso en este momento; repite la petición en un minuto si quieres el contraste"
            if self._composer.rate_limited else "el modelo o la búsqueda no respondieron"
        )
        return self._format_proposal(change, graph, tags, linked, origin, contrast, bool(related), web, reason)

    async def _web_check(self, title: str, body: str) -> WebCheck | None:
        """Contrasta una nota GENERADA con resultados reales de internet. Solo se busca el titulo: nada de la boveda sale."""
        if self._web_search is None or self._composer is None:
            return None
        results: list[dict] = []
        for query in search_queries(title):
            try:
                results = await self._web_search(query)
            except Exception:
                logger.exception("Obsidian: fallo buscando en la web")
                return WebCheck(available=False)
            if results:
                break
        return await self._composer.webcheck(title, body, results or [])

    @staticmethod
    def _provenance(body: str, web: WebCheck | None) -> tuple[str, str]:
        """(cuerpo con aviso y fuentes, texto de origen). Contrastada = sin afirmaciones contradichas y con fuentes."""
        verified = web is not None and web.available and bool(web.sources) and not web.problems
        if verified:
            notice = f"> [!info] Nota generada por PEPO y contrastada automáticamente con {len(web.sources)} fuente(s) web. Revísala igualmente."
            origin = f"generada por PEPO, contrastada con {len(web.sources)} fuente(s) web (revísala)"
        else:
            notice = "> [!warning] Nota generada por PEPO a partir de su conocimiento general. Contrasta los datos antes de fiarte."
            origin = "generada por PEPO (sin verificar)"
        body = notice + "\n\n" + body
        if web is not None and web.available and web.sources:
            body += "\n\n## Fuentes\n" + "\n".join(f"- [{title}]({url})" for title, url in web.sources)
        return body, origin

    @staticmethod
    def _format_proposal(change: Change, graph: VaultGraph, tags: list[str], linked: list[str], origin: str,
                         contrast: Contrast, had_related: bool, web: WebCheck | None, reason: str = "el modelo no respondió") -> str:
        if change.kind == "create":
            lines = [f"**Propuesta: crear la nota** `{change.path}`"]
        else:
            lines = [f"**Propuesta: añadir al final de la nota existente** `{change.path}` (ya tienes una con ese título; no creo otra)"]
        details = []
        if tags:
            details.append("Etiquetas: " + ", ".join(tags))
        if linked:
            details.append("Enlaces: " + ", ".join(f"[[{graph.notes[p].title}]]" for p in linked))
        details.append("Origen: " + origin)
        lines.append(" · ".join(details))

        if contrast.has_findings:
            lines.append("\n**Contraste con tu bóveda**")
            lines += [f"- Posible duplicado de [[{t}]]: {why}" for t, why in contrast.duplicates]
            lines += [f"- Posible contradicción con [[{t}]]: {why}" for t, why in contrast.contradictions]
        elif not contrast.available:
            lines.append(f"\nNo he podido contrastarla con tus notas ({reason}); revísala tú.")
        elif had_related:
            lines.append("\nContraste con tus notas parecidas: sin duplicados ni contradicciones.")

        if web is not None:
            if not web.available:
                lines.append(f"\nNo he podido contrastarla con internet ({reason}).")
            elif web.problems:
                lines.append("\n**Contraste con internet** (datos que las fuentes no respaldan)")
                lines += [f"- {claim}: {why}" for claim, why in web.problems]
            elif web.sources:
                lines.append(f"\nContraste con internet: nada contradicho en {len(web.sources)} fuente(s) (van al final de la nota).")
            else:
                lines.append("\nContraste con internet: las búsquedas no trataban el tema, así que la nota sigue sin verificar.")

        preview = (change.added if change.kind == "append" else change.new_text).strip()
        if len(preview) > PREVIEW_CHARS:
            preview = preview[:PREVIEW_CHARS].rsplit("\n", 1)[0] + "\n[… recortado en la vista previa]"
        # Bloque de codigo de 4 comillas: el frontmatter (---) y cualquier bloque de codigo de la nota no lo rompen.
        lines.append("\n````markdown\n" + preview + "\n````")
        lines.append("¿La escribo? Responde **sí** o **no**.")
        return "\n".join(lines)
