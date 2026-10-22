"""
desktop/code_agent/tour.py
------------------------------
Recorrido de un proyecto: el arnes (no el modelo) decide la cobertura.

Medido el 2026-10-22 con `qwen3:8b` sobre un programa real de 16 ficheros / 4.000 lineas: ante "haz un
recorrido por este programa" el modelo leyo UN fichero (`capturer.py`, 733 lineas), describio solo ese,
ignoro los otros diez y tomo el nombre de la propia aplicacion por un antivirus. Un modelo pequeño no
planifica un recorrido; lo que si hace bien es resumir lo que tiene delante. Por eso el arnes:

  1. detecta la peticion de recorrido (`is_tour_question`),
  2. construye SIN LLM un mapa real del proyecto (ficheros, resumen, funciones y lineas) que va en el prompt,
  3. exige que la respuesta nombre cada modulo y que se hayan abierto varios ficheros (`missing_units`),
  4. al terminar anade que ficheros se leyeron de verdad y cuales solo se conocen por el mapa
     (`coverage_footer`), para que el usuario sepa que parte de la respuesta es deduccion.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .index import Chunk, CodeIndex

MAP_MAX_CHARS = 5_000
MAX_FILE_UNITS = 25            # por encima, la cobertura se exige por carpeta y no por fichero
MIN_FILES_READ = 4             # un recorrido que lee menos que esto es un resumen de nombres
TOUR_FINISH_REVIEWS = 3

_ENTRY_POINTS = ("main.py", "__main__.py", "app.py", "manage.py", "run.py", "index.js", "main.js", "server.js", "index.ts")

_TOUR = re.compile(
    r"\b(?:"
    r"recorrido|recorre\b|recorrer\b|repasa\b|repasar\b|repaso\b|vision general|panoramica|"
    r"(?:revisa|revisar|analiza|analizar|explica|explicame|resume|resumeme)\s+(?:el|este|mi|todo el|todo)\s+(?:programa|proyecto|codigo|aplicacion|app|repo|repositorio)|"
    r"que\s+(?:es|hace|parece)\s+(?:este|esto|el)\s+(?:programa|proyecto|codigo|aplicacion|app)|"
    r"de que (?:va|trata)\s+(?:este|el)\s+(?:programa|proyecto|codigo|aplicacion|app)"
    r")",
)


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def is_tour_question(text: str) -> bool:
    """True si el usuario pide una vision general del programa (no una pregunta concreta sobre el codigo)."""
    return bool(_TOUR.search(_plain(text or "")))


@dataclass
class ModuleOutline:
    path: str
    lines: int
    doc: str = ""
    classes: list[tuple[str, int, int]] = field(default_factory=list)      # (nombre, linea, n_metodos)
    functions: list[tuple[str, int]] = field(default_factory=list)         # (nombre, linea)
    is_test: bool = False

    @property
    def is_entry(self) -> bool:
        pure = PurePosixPath(self.path)
        return pure.name == "__main__.py" or (pure.name in _ENTRY_POINTS and len(pure.parts) == 1)


def _is_test_path(path: str) -> bool:
    return "/tests/" in f"/{path}" or PurePosixPath(path).name.startswith("test_")


def _first_doc_line(chunks: list[Chunk]) -> str:
    """Primera linea con contenido del docstring del modulo (salta la ruta y las rayas decorativas)."""
    module = next((c for c in chunks if c.kind == "modulo"), None)
    if module is None:
        return ""
    match = re.search(r'("""|\'\'\')(.*?)\1', "\n".join(module.lines), re.DOTALL)
    if not match:
        return ""
    for raw in match.group(2).splitlines():
        line = raw.strip()
        if not line or set(line) <= set("-=_*# "):
            continue
        if re.fullmatch(r"[\w./\\-]+\.\w+", line):          # la linea es solo la ruta del fichero
            continue
        return line[:110]
    return ""


def build_outlines(index: CodeIndex) -> list[ModuleOutline]:
    """Esquema de cada fichero con codigo: ordenado con los puntos de entrada primero."""
    outlines: list[ModuleOutline] = []
    for path in index.file_paths():
        chunks = index.file_chunks(path)
        classes = [c for c in chunks if c.kind == "clase"]
        functions = [c for c in chunks if c.kind == "funcion"]
        doc = _first_doc_line(chunks)
        if not classes and not functions and not doc:
            continue                                       # __init__.py vacios, datos, texto suelto
        outlines.append(ModuleOutline(
            path=path,
            lines=index.line_count(path),
            doc=doc,
            classes=[
                (c.name, c.start, sum(1 for m in chunks if m.kind == "metodo" and m.name.startswith(c.name + ".")))
                for c in classes
            ],
            functions=[(f.name, f.start) for f in functions],
            is_test=_is_test_path(path),
        ))
    outlines.sort(key=lambda o: (o.is_test, not o.is_entry, o.path.count("/"), o.path))
    return outlines


def _format_module(outline: ModuleOutline, level: int) -> str:
    head = f"{outline.path} ({outline.lines} lin.)"
    if outline.is_entry:
        head += " [punto de entrada]"
    if outline.doc and level <= 2:
        head += f" — {outline.doc}"
    if level >= 3:
        return head
    parts = []
    classes = outline.classes
    functions = outline.functions
    if level >= 1:
        functions = [f for f in functions if not f[0].startswith("_")]
    if level >= 2:
        classes, functions = classes[:4], functions[:6]
    if classes:
        parts.append("clases: " + ", ".join(f"{n}:{line}" + (f" ({m} metodos)" if m else "") for n, line, m in classes))
    if functions:
        parts.append("funciones: " + ", ".join(f"{n}:{line}" for n, line in functions))
    return head + ("\n    " + " · ".join(parts) if parts else "")


def format_map(outlines: list[ModuleOutline], max_chars: int = MAP_MAX_CHARS) -> str:
    """El mapa cabe en `max_chars`: si no, se va degradando (sin helpers privados, solo lo principal, solo ficheros)."""
    shown = [o for o in outlines if not o.is_test] or outlines
    tests = [o for o in outlines if o.is_test]
    text = ""
    for level in range(4):
        text = "\n".join(_format_module(o, level) for o in shown)
        if len(text) <= max_chars:
            break
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n[... mapa recortado: proyecto grande]"
    if tests:
        text += f"\n(+ {len(tests)} ficheros de tests, no listados)"
    return text


# ── Cobertura ────────────────────────────────────────────────────────────────

def coverage_units(outlines: list[ModuleOutline]) -> list[str]:
    """Lo que la respuesta debe nombrar: un fichero cada uno o, en proyectos grandes, una carpeta cada una."""
    files = [o.path for o in outlines if not o.is_test]
    if len(files) <= MAX_FILE_UNITS:
        return files
    folders = {str(PurePosixPath(p).parent) for p in files}
    return sorted(f for f in folders if f != ".")


def missing_units(answer: str, units: list[str]) -> list[str]:
    """Unidades que la respuesta no nombra (ni por ruta ni por nombre de fichero/carpeta)."""
    text = _plain(answer).replace("\\", "/")
    missing = []
    for unit in units:
        name = PurePosixPath(unit).name
        if _plain(unit) not in text and _plain(name) not in text:
            missing.append(unit)
    return missing


def coverage_footer(outlines: list[ModuleOutline], opened: set[str]) -> str:
    """Pie honesto del recorrido: que se leyo de verdad y que solo se conoce por el mapa (nombres y firmas)."""
    files = [o.path for o in outlines if not o.is_test]
    if not files:
        return ""
    read = [p for p in files if p in opened]
    unread = [p for p in files if p not in opened]
    lines = [f"Cobertura de este recorrido: lei {len(read)} de {len(files)} ficheros."]
    if read:
        lines.append("Leidos: " + ", ".join(read) + ".")
    if unread:
        lines.append(
            "NO abiertos (solo conozco sus nombres y funciones por el mapa, asi que lo que digo de ellos es una "
            "deduccion): " + ", ".join(unread) + "."
        )
    return "\n\n---\n" + "\n".join(lines)
