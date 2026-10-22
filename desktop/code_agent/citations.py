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
     argumentos de una llamada): asi no se pueden citar de memoria ficheros nunca abiertos,
  4. el rango es acotado (<= MAX_RANGE_LINES): medido el 2026-10-22, un recorrido citaba tramos de
     60-100 lineas que eran simplemente lo que el modelo habia leido, no donde esta cada cosa, y
  5. si la misma linea de la respuesta nombra entre comillas una funcion/clase de ese fichero, esa
     definicion tiene que caer dentro del rango citado (una cita con linea equivocada).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

from .workspace import Workspace, WorkspaceError

SymbolsOf = Callable[[str], list[tuple[str, int, int]]]

_CITATION = re.compile(r"([\w./\\-]+\.[A-Za-z0-9]+)\s*(?:#L|:L|[:#])\s*(\d+)(?:\s*[-–]\s*(\d+))?")
MAX_CITATIONS_CHECKED = 12
MAX_RANGE_LINES = 60
_BACKTICKED_NAME = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`")


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


def _cited_with_line(answer: str) -> list[tuple[str, int, int, str, int]]:
    """(ruta, inicio, fin, texto_de_su_linea, citas_en_esa_linea) por cada cita de la respuesta."""
    lines = (answer or "").splitlines()
    found = []
    for line in lines:
        matches = list(_CITATION.finditer(line))
        for match in matches:
            start = int(match.group(2))
            end = int(match.group(3)) if match.group(3) else start
            found.append((match.group(1).replace("\\", "/"), start, max(end, start), line, len(matches)))
    return found


def _symbol_mismatch(line: str, relative: str, start: int, end: int, symbols_of: SymbolsOf | None) -> str | None:
    """Funcion/clase nombrada entre comillas en la linea de la cita que esta definida en ese fichero pero FUERA del rango."""
    if symbols_of is None:
        return None
    defs = symbols_of(relative)
    if not defs:
        return None
    for name in dict.fromkeys(_BACKTICKED_NAME.findall(line)):
        matching = [(n, s, e) for n, s, e in defs if n == name or n.split(".")[-1] == name]
        if matching and not any(s <= end + 2 and e >= start - 2 for _, s, e in matching):
            _, first, last = matching[0]
            return f"`{name}` esta definida en {relative}:{first}-{last}, no en las lineas citadas."
    return None


def verify_citations(
    answer: str, ws: Workspace, seen_text: str, known_paths: Callable[[], Iterable[str]] = lambda: (),
    symbols_of: SymbolsOf | None = None,
) -> tuple[list[tuple[str, int, int]], list[str]]:
    """Devuelve (citas_validas, problemas). Sin citas, `problemas` queda vacio: eso lo trata quien llama."""
    valid: list[tuple[str, int, int]] = []
    problems: list[str] = []
    seen_lower = seen_text.lower().replace("\\", "/")
    for cited, start, end, line, in_line in _cited_with_line(answer)[:MAX_CITATIONS_CHECKED]:
        label = f"`{cited}:{start}" + (f"-{end}" if end != start else "") + "`"
        real = _resolve(ws, cited, known_paths)
        if real is None:
            problems.append(f"{label}: ese fichero no existe en el proyecto (o es ambiguo).")
            continue
        lines = _line_count(real)
        if start < 1 or end > lines:
            problems.append(f"{label}: {ws.rel(real)} solo tiene {lines} lineas.")
            continue
        if end - start + 1 > MAX_RANGE_LINES:
            problems.append(
                f"{label}: el rango es demasiado ancho ({end - start + 1} lineas, maximo {MAX_RANGE_LINES}); cita la linea "
                "de la funcion concreta que respalda la afirmacion, no todo lo que leiste."
            )
            continue
        relative = ws.rel(real).lower()
        if relative not in seen_lower and Path(relative).name not in seen_lower:
            problems.append(f"{label}: no has visto ese fichero en esta tarea; leelo con read_file antes de citarlo.")
            continue
        mismatch = _symbol_mismatch(line, ws.rel(real), start, end, symbols_of) if in_line == 1 else None
        if mismatch:
            problems.append(f"{label}: {mismatch}")
            continue
        valid.append((ws.rel(real), start, end))
    return valid, problems
