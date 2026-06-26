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
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)

    return repo_root, app_root
