"""Shared import path bootstrap for Open-Nexus desktop flows."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_desktop_import_paths() -> tuple[Path, Path]:
    """Expose repo root and /app as importable roots for desktop runtime."""
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"

    for candidate in (repo_root, app_root):
        candidate_str = str(candidate)
        # Reinsertar siempre al frente, no solo si falta: si ya estaba
        # presente mas atras (p.ej. via PYTHONPATH precargado por el script
        # de arranque), dejarlo ahi permite que desktop/main.py (que se
        # inserta a si mismo en sys.path[0] antes de llamar aqui) tape
        # config.py de la raiz con desktop/config.py — mismo nombre de
        # modulo, resultado distinto.
        if candidate_str in sys.path:
            sys.path.remove(candidate_str)
        sys.path.insert(0, candidate_str)

    return repo_root, app_root
