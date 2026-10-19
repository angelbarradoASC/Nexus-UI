"""
desktop/code_agent/tools.py
------------------------------
Herramientas de SOLO LECTURA del agente de codigo (Fase 1 del plan). Se ejecutan
sin pedir confirmacion porque no tocan nada. Todas pasan por `Workspace` (sandbox
+ lista negra) y todo texto que sale hacia el LLM pasa por `redact()`.

Cada funcion devuelve un string apto para el LLM: los errores esperables (ruta
fuera del workspace, fichero que no existe...) vuelven como texto, no como
excepcion, para que el modelo pueda corregirse.
"""

from __future__ import annotations

import fnmatch
import itertools
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .workspace import SKIP_DIRS, Workspace, WorkspaceError, redact

READ_MAX_LINES = 400
READ_MAX_CHARS = 40_000
MAX_FILE_BYTES = 5 * 1024 * 1024
GREP_MAX_MATCHES = 100
GREP_MAX_FILE_BYTES = 1024 * 1024
GREP_MAX_SECONDS = 10.0
GLOB_MAX_RESULTS = 200
LIST_MAX_ENTRIES = 200
GIT_MAX_CHARS = 20_000
GIT_TIMEOUT = 15

_SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


def _scrubbed_env() -> dict[str, str]:
    """Entorno para subprocesos: sin claves de API ni credenciales."""
    env = {k: v for k, v in os.environ.items() if not any(h in k.upper() for h in _SECRET_ENV_HINTS)}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return True


# ── Tools de lectura ─────────────────────────────────────────────────────────

def read_file(ws: Workspace, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    try:
        target = ws.resolve_readable(path)
    except WorkspaceError as exc:
        return f"No permitido: {exc}"
    if not target.exists():
        return f"No existe el fichero: {ws.rel(target)}"
    if target.is_dir():
        return f"{ws.rel(target)} es una carpeta; usa list_directory."
    try:
        size = target.stat().st_size
    except OSError as exc:
        return f"No se pudo leer {ws.rel(target)}: {exc}"
    if size > MAX_FILE_BYTES:
        return f"{ws.rel(target)} es demasiado grande ({size // 1024} KB, maximo {MAX_FILE_BYTES // 1024} KB)."
    if _is_binary(target):
        return f"{ws.rel(target)} parece un fichero binario; no se puede leer como texto."

    first = max(int(start_line or 1), 1)
    last = int(end_line) if end_line else first + READ_MAX_LINES - 1
    last = min(last, first + READ_MAX_LINES - 1)
    if last < first:
        return "end_line debe ser mayor o igual que start_line."

    try:
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            window = list(itertools.islice(handle, first - 1, last))
            more = next(handle, None) is not None
    except OSError as exc:
        return f"No se pudo leer {ws.rel(target)}: {exc}"

    if not window:
        return f"{ws.rel(target)}: no hay lineas desde la {first} (el fichero es mas corto)."

    lines: list[str] = []
    chars = 0
    shown_last = first - 1
    for offset, raw_line in enumerate(window):
        numbered = f"{first + offset:>6}\t{raw_line.rstrip(chr(10)).rstrip(chr(13))}"
        chars += len(numbered) + 1
        if chars > READ_MAX_CHARS:
            more = True
            break
        lines.append(numbered)
        shown_last = first + offset

    header = f"{ws.rel(target)} (lineas {first}-{shown_last})"
    footer = f"\n[... hay mas lineas; sigue con start_line={shown_last + 1}]" if more else ""
    return redact(f"{header}\n" + "\n".join(lines) + footer)


def list_directory(ws: Workspace, path: str = ".") -> str:
    try:
        target = ws.resolve_readable(path)
    except WorkspaceError as exc:
        return f"No permitido: {exc}"
    if not target.exists():
        return f"No existe la carpeta: {ws.rel(target)}"
    if not target.is_dir():
        return f"{ws.rel(target)} es un fichero; usa read_file."
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        return f"No se pudo listar {ws.rel(target)}: {exc}"

    out: list[str] = []
    hidden = 0
    for entry in entries:
        if ws.is_denied(entry):
            hidden += 1
            continue
        if entry.is_dir():
            out.append(f"[dir]  {entry.name}/" + ("  (omitida en busquedas)" if entry.name.lower() in SKIP_DIRS else ""))
        else:
            try:
                out.append(f"{entry.stat().st_size:>9}  {entry.name}")
            except OSError:
                out.append(f"{'?':>9}  {entry.name}")
        if len(out) >= LIST_MAX_ENTRIES:
            out.append(f"[... hay mas entradas; usa glob o una subcarpeta]")
            break
    if hidden:
        out.append(f"({hidden} entradas ocultas por seguridad)")
    return redact(f"{ws.rel(target)}/ — {len(entries)} entradas\n" + ("\n".join(out) if out else "(vacia)"))


def glob_files(ws: Workspace, pattern: str) -> str:
    pattern = (pattern or "").strip()
    if not pattern:
        return "Falta el patron (ej. **/*.py)."
    if pattern.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", pattern) or ".." in Path(pattern).parts:
        return "No permitido: el patron debe ser relativo al workspace y sin '..'."
    found: list[str] = []
    for file_path in ws.iter_files():
        relative = ws.rel(file_path)
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(file_path.name, pattern):
            found.append(relative)
            if len(found) >= GLOB_MAX_RESULTS:
                break
    if not found:
        return f"Ningun fichero coincide con {pattern}."
    suffix = f"\n[... recortado a {GLOB_MAX_RESULTS}; afina el patron]" if len(found) >= GLOB_MAX_RESULTS else ""
    return redact("\n".join(found) + suffix)


def grep(
    ws: Workspace,
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    ignore_case: bool = False,
) -> str:
    if not (pattern or "").strip():
        return "Falta el patron de busqueda."
    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        return f"Expresion regular invalida: {exc}"
    try:
        base = ws.resolve_readable(path)
    except WorkspaceError as exc:
        return f"No permitido: {exc}"
    if not base.exists():
        return f"No existe: {ws.rel(base)}"

    matches: list[str] = []
    started = time.monotonic()
    timed_out = False
    for file_path in ws.iter_files(base):
        if glob and not (fnmatch.fnmatch(file_path.name, glob) or fnmatch.fnmatch(ws.rel(file_path), glob)):
            continue
        if time.monotonic() - started > GREP_MAX_SECONDS:
            timed_out = True
            break
        try:
            if file_path.stat().st_size > GREP_MAX_FILE_BYTES or _is_binary(file_path):
                continue
            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, start=1):
                    if regex.search(line):
                        text = line.rstrip("\r\n")
                        matches.append(f"{ws.rel(file_path)}:{number}: {text[:200]}")
                        if len(matches) >= GREP_MAX_MATCHES:
                            break
        except OSError:
            continue
        if len(matches) >= GREP_MAX_MATCHES:
            break

    if not matches:
        return "Sin coincidencias." + (" (busqueda cortada por tiempo)" if timed_out else "")
    notes = []
    if len(matches) >= GREP_MAX_MATCHES:
        notes.append(f"recortado a {GREP_MAX_MATCHES} coincidencias; afina el patron o la ruta")
    if timed_out:
        notes.append("busqueda cortada por tiempo")
    return redact("\n".join(matches) + (f"\n[... {'; '.join(notes)}]" if notes else ""))


# ── git (solo lectura: comandos fijos, nunca el texto del LLM como comando) ─

def _git(ws: Workspace, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=ws.root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT, env=_scrubbed_env(),
        )
    except FileNotFoundError:
        return "git no esta instalado o no esta en el PATH."
    except subprocess.TimeoutExpired:
        return f"git tardo mas de {GIT_TIMEOUT}s y se cancelo."
    output = (completed.stdout or "") + (("\n" + completed.stderr) if completed.returncode and completed.stderr else "")
    output = output.strip() or "(sin salida)"
    if len(output) > GIT_MAX_CHARS:
        output = output[:GIT_MAX_CHARS] + "\n[... salida recortada]"
    return redact(output)


def git_status(ws: Workspace) -> str:
    return _git(ws, ["status", "--short", "--branch"])


def git_diff(ws: Workspace, path: str | None = None, staged: bool = False) -> str:
    args = ["diff", "--no-color"] + (["--staged"] if staged else [])
    if path:
        try:
            target = ws.resolve_readable(path)
        except WorkspaceError as exc:
            return f"No permitido: {exc}"
        args += ["--", ws.rel(target)]
    return _git(ws, args)


def git_log(ws: Workspace, count: int = 10) -> str:
    return _git(ws, ["log", "--oneline", "--no-color", f"-n{min(max(int(count), 1), 30)}"])


# ── Esquemas para el LLM (formato OpenAI) ────────────────────────────────────

def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


READ_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "read_file",
        "Lee un fichero del proyecto con numeros de linea. Maximo ~400 lineas por llamada: para ficheros largos usa start_line/end_line.",
        {
            "path": {"type": "string", "description": "Ruta relativa al proyecto."},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        ["path"],
    ),
    _schema(
        "grep",
        "Busca una expresion regular en los ficheros del proyecto. Devuelve ruta:linea: texto. Usala ANTES de leer ficheros enteros.",
        {
            "pattern": {"type": "string", "description": "Expresion regular (Python)."},
            "path": {"type": "string", "description": "Carpeta o fichero donde buscar (por defecto, todo el proyecto)."},
            "glob": {"type": "string", "description": "Filtro de nombre, ej. *.py"},
            "ignore_case": {"type": "boolean"},
        },
        ["pattern"],
    ),
    _schema(
        "glob",
        "Lista ficheros del proyecto que coinciden con un patron, ej. **/*.py o tests/*.py.",
        {"pattern": {"type": "string"}},
        ["pattern"],
    ),
    _schema(
        "list_directory",
        "Lista una carpeta del proyecto (por defecto la raiz).",
        {"path": {"type": "string"}},
    ),
    _schema("git_status", "Estado de git del proyecto (rama y ficheros modificados). Solo lectura.", {}),
    _schema(
        "git_diff",
        "Diff de git sin confirmar. Solo lectura.",
        {"path": {"type": "string"}, "staged": {"type": "boolean"}},
    ),
    _schema("git_log", "Ultimos commits (una linea cada uno). Solo lectura.", {"count": {"type": "integer"}}),
]


def run_read_tool(ws: Workspace, name: str, args: dict[str, Any]) -> str | None:
    """Despacha una tool de lectura. None si `name` no es una de ellas."""
    if name == "read_file":
        return read_file(ws, str(args.get("path", "")), args.get("start_line"), args.get("end_line"))
    if name == "grep":
        return grep(
            ws, str(args.get("pattern", "")), str(args.get("path") or "."),
            args.get("glob"), bool(args.get("ignore_case", False)),
        )
    if name == "glob":
        return glob_files(ws, str(args.get("pattern", "")))
    if name == "list_directory":
        return list_directory(ws, str(args.get("path") or "."))
    if name == "git_status":
        return git_status(ws)
    if name == "git_diff":
        return git_diff(ws, args.get("path"), bool(args.get("staged", False)))
    if name == "git_log":
        return git_log(ws, args.get("count") or 10)
    return None
