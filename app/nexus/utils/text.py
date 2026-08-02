"""Shared text normalization utilities for Nexus."""

from __future__ import annotations

import unicodedata
from typing import Any


def normalize_text(value: Any) -> str:
    """Normalize text to lowercase ASCII for fuzzy matching and comparisons.

    Strips accents/diacritics (NFKD → ASCII), lowercases, and collapses whitespace.
    This was previously defined independently in routes/prospecting.py,
    prospecting/orchestrator.py, and prospecting/service.py.
    """
    raw = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = raw.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())
