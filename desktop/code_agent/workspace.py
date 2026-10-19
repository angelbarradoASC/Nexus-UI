"""
desktop/code_agent/workspace.py
----------------------------------
Sandbox del "modo codigo" de PEPO (docs/PLAN_PEPO_MODO_CODIGO.md, D4).

Todo acceso a ficheros del agente de codigo pasa por aqui:

- Las rutas se resuelven (symlinks y junctions incluidos) y TIENEN que quedar
  dentro de la carpeta de trabajo. Se rechazan `..` que escapan, rutas absolutas
  de otra unidad, UNC, flujos alternos NTFS (`fichero:stream`) y nombres
  reservados de Windows (CON, NUL...).
- Lista negra de ficheros sensibles (.env, claves, credenciales): ni se leen ni
  salen en busquedas, porque su contenido viaja a un LLM en la nube.
- `redact()` tapa patrones de claves/tokens en cualquier texto que vaya al LLM,
  por si un secreto aparece dentro de un fichero que si se puede leer.

El contenido de los ficheros es DATO, nunca instruccion: nada de este modulo
interpreta texto leido.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator
from pathlib import Path


class WorkspaceError(Exception):
    """Ruta o carpeta de trabajo no permitida. El mensaje es apto para devolverlo al LLM."""


# Ficheros que no se leen ni se listan (comparacion en minusculas, fnmatch).
_DENIED_FILE_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.env",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    "credentials*", "*.credentials", ".netrc", ".pgpass", "*.token", "token.json",
    "secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml",
)

# Carpetas inaccesibles para lectura (el agente puede usar git por la via de las tools de git).
_DENIED_DIRS: frozenset[str] = frozenset({".git", ".ssh", ".aws", ".gnupg"})

# Carpetas que se saltan en busquedas/listados recursivos (ruido, no seguridad).
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".idea", "dist", "build", "site-packages",
})

_WINDOWS_RESERVED: frozenset[str] = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)

# Patrones de secretos que se tapan en lo que vuelve al LLM.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "«CLAVE PRIVADA REDACTADA»"),
    (re.compile(r"\b(?:sk|gsk|ghp|gho|ghs|github_pat|xox[abprs]|AKIA|AIza)[-_A-Za-z0-9]{16,}"), "«TOKEN REDACTADO»"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer «REDACTADO»"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|secret|token|passwd|password|contrase(?:ñ|n)a|authorization|client[_-]?secret)"
            r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{8,})"
        ),
        r"\1«REDACTADO»",
    ),
)


def redact(text: str) -> str:
    """Tapa claves/tokens/contraseñas reconocibles. No es infalible: es una
    segunda red detras de la lista negra de ficheros."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def is_denied_name(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pattern) for pattern in _DENIED_FILE_PATTERNS)


def validate_workspace_root(raw: str) -> Path:
    """Valida una carpeta candidata a workspace: debe existir, ser carpeta y no
    ser demasiado amplia (raiz de unidad, perfil de usuario, Windows...)."""
    if not raw or not str(raw).strip() or "\x00" in str(raw):
        raise WorkspaceError("Ruta de carpeta vacia o invalida.")
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        raise WorkspaceError("La carpeta de trabajo debe ser una ruta absoluta.")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise WorkspaceError(f"La carpeta no existe: {raw}")
    if not resolved.is_dir():
        raise WorkspaceError(f"No es una carpeta: {raw}")

    home = Path.home().resolve()
    too_broad = {resolved.anchor and Path(resolved.anchor).resolve(), home, home.parent}
    for env in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(env)
        if value:
            too_broad.add(Path(value).resolve())
    if resolved in too_broad or resolved.parent == resolved:
        raise WorkspaceError(f"Carpeta demasiado amplia para ser un proyecto: {resolved}. Elige la carpeta del proyecto.")
    return resolved


class Workspace:
    """Carpeta de trabajo del agente de codigo."""

    def __init__(self, root: str | Path) -> None:
        self.root = validate_workspace_root(str(root))
        self._root_key = os.path.normcase(str(self.root))

    def __repr__(self) -> str:  # pragma: no cover - depuracion
        return f"Workspace({self.root})"

    # ── Resolucion y comprobaciones ──────────────────────────────────────────

    def _inside(self, resolved: Path) -> bool:
        key = os.path.normcase(str(resolved))
        return key == self._root_key or key.startswith(self._root_key + os.sep)

    def resolve(self, raw: str | None) -> Path:
        """Ruta (relativa al workspace o absoluta dentro de el) -> Path real
        dentro del workspace. No exige que exista."""
        text = (raw or ".").strip() or "."
        if "\x00" in text:
            raise WorkspaceError("Ruta invalida.")
        # ':' solo es valido como unidad en una ruta absoluta (C:\...); cualquier otro
        # caso es un flujo alterno de NTFS (fichero.txt:stream) o una ruta relativa a unidad.
        stripped = text[2:] if re.match(r"^[A-Za-z]:[\\/]", text) else text
        if ":" in stripped:
            raise WorkspaceError(f"Ruta no permitida: {raw}")
        if text.startswith(("\\\\", "//")):
            raise WorkspaceError(f"Ruta de red no permitida: {raw}")

        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        for part in candidate.parts:
            stem = part.split(".")[0].lower()
            if stem in _WINDOWS_RESERVED:
                raise WorkspaceError(f"Nombre reservado de Windows no permitido: {part}")
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceError(f"No se pudo resolver la ruta {raw}: {exc}")
        if not self._inside(resolved):
            raise WorkspaceError(f"Fuera de la carpeta de trabajo ({self.root}): {raw}")
        return resolved

    def is_denied(self, path: Path) -> bool:
        """True si la ruta (ya dentro del workspace) es sensible: fichero o carpeta de la lista negra."""
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return True
        parts = relative.parts
        if any(part.lower() in _DENIED_DIRS for part in parts[:-1]):
            return True
        if parts and parts[-1].lower() in _DENIED_DIRS:
            return True
        return bool(parts) and is_denied_name(parts[-1])

    def resolve_readable(self, raw: str | None) -> Path:
        """resolve() + lista negra. Es lo que usan las tools de lectura."""
        path = self.resolve(raw)
        if self.is_denied(path):
            raise WorkspaceError(f"Ruta protegida por seguridad (credenciales o carpeta interna): {self.rel(path)}")
        return path

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(path)

    # ── Recorrido ────────────────────────────────────────────────────────────

    def iter_files(self, base: Path | None = None) -> Iterator[Path]:
        """Ficheros bajo `base` (por defecto el workspace), sin carpetas de ruido
        ni ficheros protegidos. No sigue symlinks a carpetas."""
        start = base or self.root
        if start.is_file():
            if not self.is_denied(start):
                yield start
            return
        for current, dirs, files in os.walk(start, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(
                d for d in dirs
                if d.lower() not in SKIP_DIRS and d.lower() not in _DENIED_DIRS and not (current_path / d).is_symlink()
            )
            for name in sorted(files):
                file_path = current_path / name
                if is_denied_name(name) or file_path.is_symlink():
                    continue
                yield file_path
