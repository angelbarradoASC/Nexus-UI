"""
desktop/obsidian/audit.py
----------------------------
Informe determinista de una boveda: que hay, que esta roto y que se puede mejorar. Sin LLM.

Cada hallazgo lleva ruta y linea para poder arreglarlo (fase 2) o abrirlo en Obsidian.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .graph import Mention, VaultGraph

_CONFLICT_NAME = re.compile(r"(\(conflict|conflicto|\bcopia\b|\bcopy\b|\(\d+\)$|-\w+-\d{4}-\d{2}-\d{2})", re.IGNORECASE)


@dataclass
class AuditReport:
    vault_name: str
    notes: int = 0
    links: int = 0
    with_frontmatter: int = 0
    without_tags: int = 0
    skipped_protected: int = 0
    broken: list[tuple[str, int, str]] = field(default_factory=list)                 # (nota, linea, enlace)
    missing_attachments: list[tuple[str, int, str]] = field(default_factory=list)
    ambiguous: list[tuple[str, int, str, list[str]]] = field(default_factory=list)    # (nota, linea, enlace, candidatas)
    orphans: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    no_frontmatter: list[str] = field(default_factory=list)
    duplicate_titles: dict[str, list[str]] = field(default_factory=dict)
    conflict_copies: list[str] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)

    @property
    def issues(self) -> int:
        return len(self.broken) + len(self.ambiguous) + len(self.empty) + len(self.duplicate_titles) + len(self.conflict_copies)


def audit_graph(graph: VaultGraph, vault_name: str = "", skipped_protected: int = 0) -> AuditReport:
    report = AuditReport(vault_name=vault_name, notes=len(graph.notes), skipped_protected=skipped_protected)
    titles: dict[str, list[str]] = {}
    for path, note in sorted(graph.notes.items()):
        report.links += len(note.links)
        report.with_frontmatter += 1 if note.has_frontmatter else 0
        if not note.has_frontmatter:
            report.no_frontmatter.append(path)
        if not note.tags:
            report.without_tags += 1
        if note.is_empty:
            report.empty.append(path)
        if _CONFLICT_NAME.search(note.title):
            report.conflict_copies.append(path)
        titles.setdefault(note.title.lower(), []).append(path)

        for link, resolution in graph.resolutions.get(path, []):
            label = link.raw
            if resolution.status == "broken":
                report.broken.append((path, link.line, label))
            elif resolution.status == "missing_attachment":
                report.missing_attachments.append((path, link.line, label))
            elif resolution.status == "ambiguous":
                report.ambiguous.append((path, link.line, label, resolution.candidates))

        if not graph.links_to(path) and not graph.outgoing_notes(path):
            report.orphans.append(path)

    report.duplicate_titles = {title: paths for title, paths in titles.items() if len(paths) > 1}
    report.mentions = graph.unlinked_mentions()
    return report


def _more(total: int, shown: int) -> str:
    return f"\n  … y {total - shown} más" if total > shown else ""


def _bullets(items: list[str], limit: int) -> str:
    return "\n".join(f"- {item}" for item in items[:limit]) + _more(len(items), limit)


def format_report(report: AuditReport, limit: int = 6) -> str:
    """Informe en Markdown para el chat: resumen, y por cada problema los primeros casos con ruta y linea."""
    name = f" «{report.vault_name}»" if report.vault_name else ""
    lines = [f"**Repaso de la bóveda{name}**: {report.notes} notas, {report.links} enlaces."]
    if not report.notes:
        return lines[0] + " No hay ninguna nota todavía."

    lines.append(
        f"Con frontmatter: {report.with_frontmatter} de {report.notes} · sin etiquetas: {report.without_tags}."
        + (f" ({report.skipped_protected} ficheros con nombre de credenciales no se han leído.)" if report.skipped_protected else "")
    )

    sections: list[tuple[str, list[str]]] = [
        ("Enlaces rotos (apuntan a una nota que no existe)", [f"`{p}` línea {n}: {raw}" for p, n, raw in report.broken]),
        ("Enlaces ambiguos (hay varias notas con ese nombre)", [f"`{p}` línea {n}: {raw} → {', '.join(f'`{c}`' for c in cands[:3])}" for p, n, raw, cands in report.ambiguous]),
        ("Adjuntos que faltan", [f"`{p}` línea {n}: {raw}" for p, n, raw in report.missing_attachments]),
        ("Notas vacías", [f"`{p}`" for p in report.empty]),
        ("Títulos duplicados", [f"«{PurePosixPath(paths[0]).stem}»: " + ", ".join(f"`{p}`" for p in paths) for paths in report.duplicate_titles.values()]),
        ("Posibles copias por conflicto de sincronización", [f"`{p}`" for p in report.conflict_copies]),
        ("Notas huérfanas (nadie las enlaza y no enlazan a nada)", [f"`{p}`" for p in report.orphans]),
        (
            "Menciones sin enlazar (la nota nombra a otra pero no la enlaza)",
            [f"`{m.source}` línea {m.line}: «{m.title}» → [[{PurePosixPath(m.target).stem}]]" for m in report.mentions],
        ),
    ]
    clean = True
    for title, items in sections:
        if items:
            clean = False
            lines.append(f"\n**{title}: {len(items)}**\n{_bullets(items, limit)}")
    if report.no_frontmatter and report.notes > 1:
        lines.append(f"\n**Notas sin frontmatter: {len(report.no_frontmatter)}** (fecha, etiquetas y alias).")
    if clean and not report.no_frontmatter:
        lines.append("\nNo he encontrado problemas.")
    return "\n".join(lines)
