"""
desktop/code_agent/citations.py
-----------------------------------
Citas `ruta:linea` de las respuestas del agente y su verificacion automatica.

Medido el 2026-10-20: con `qwen3:8b`, 4 de las 8 primeras respuestas a preguntas nuevas señalaban el
fichero correcto pero NO citaban una linea (y otras citaban lineas reales pero equivocadas o
inventadas). El arnes puede exigirlo: antes de aceptar la respuesta comprueba que cada cita es
verificable y, si no, la devuelve al modelo con el motivo concreto.

Una cita es valida si:
  1. el fichero existe dentro de la carpeta de trabajo (y no esta protegido),
  2. la linea (y el fin del rango) caben en el fichero, y
  3. el modelo ha VISTO ese fichero en esta tarea (aparece en un resultado de herramienta o en los
     argumentos de una llamada): asi no se pueden citar de memoria ficheros nunca abiertos.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

from .workspace import Workspace, WorkspaceError

_CITATION = re.compile(r"([\w./\\-]+\.[A-Za-z0-9]+)\s*(?:#L|:L|[:#])\s*(\d+)(?:\s*[-–]\s*(\d+))?")
MAX_CITATIONS_CHECKED = 12


def citations(answer: str) -> list[tuple[str, int, int]]:
    """(ruta, linea_inicio, linea_fin) de cada `ruta:linea` o `ruta:desde-hasta` del texto."""
    found = []
    for match in _CITATION.finditer(answer or ""):
        start = int(match.group(2))
        end = int(match.group(3)) if match.group(3) else start
        found.append((match.group(1).replace("\\", "/"), start, max(end, start)))
    return found


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _resolve(ws: Workspace, cited: str, known_paths: Callable[[], Iterable[str]]) -> Path | None:
    """Ruta citada -> fichero real. Acepta la ruta relativa al proyecto o solo el final de la ruta
    (`skill_router.py`) si es inequivoco entre los ficheros del proyecto."""
    try:
        candidate = ws.resolve_readable(cited)
        if candidate.is_file():
            return candidate
    except WorkspaceError:
        pass
    matches = [p for p in known_paths() if p == cited or p.endswith("/" + cited)]
    if len(matches) == 1:
        try:
            return ws.resolve_readable(matches[0])
        except WorkspaceError:
            return None
    return None


def verify_citations(
    answer: str, ws: Workspace, seen_text: str, known_paths: Callable[[], Iterable[str]] = lambda: (),
) -> tuple[list[tuple[str, int, int]], list[str]]:
    """Devuelve (citas_validas, problemas). Sin citas, `problemas` queda vacio: eso lo trata quien llama."""
    valid: list[tuple[str, int, int]] = []
    problems: list[str] = []
    seen_lower = seen_text.lower().replace("\\", "/")
    for cited, start, end in citations(answer)[:MAX_CITATIONS_CHECKED]:
        label = f"`{cited}:{start}" + (f"-{end}" if end != start else "") + "`"
        real = _resolve(ws, cited, known_paths)
        if real is None:
            problems.append(f"{label}: ese fichero no existe en el proyecto (o es ambiguo).")
            continue
        lines = _line_count(real)
        if start < 1 or end > lines:
            problems.append(f"{label}: {ws.rel(real)} solo tiene {lines} lineas.")
            continue
        relative = ws.rel(real).lower()
        if relative not in seen_lower and Path(relative).name not in seen_lower:
            problems.append(f"{label}: no has visto ese fichero en esta tarea; leelo con read_file antes de citarlo.")
            continue
        valid.append((ws.rel(real), start, end))
    return valid, problems
