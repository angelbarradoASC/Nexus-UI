"""Shared text normalization utilities for Nexus."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_CATEGORY_SPLIT_RE = re.compile(r"\s+(?:y|e)\s+|,", re.IGNORECASE)


def normalize_text(value: Any) -> str:
    """Normalize text to lowercase ASCII for fuzzy matching and comparisons.

    Strips accents/diacritics (NFKD → ASCII), lowercases, and collapses whitespace.
    This was previously defined independently in routes/prospecting.py,
    prospecting/orchestrator.py, and prospecting/service.py.
    """
    raw = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = raw.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def split_target_categories(text: str, *, max_categories: int = 4) -> list[str]:
    """Split a free-text business description into individual category phrases.

    "peluquerías, talleres mecánicos y restaurantes" ->
    ["peluquerías", "talleres mecánicos", "restaurantes"].

    Una descripcion multi-categoria usada TAL CUAL como una sola query de
    busqueda no representa un negocio concreto — DDG/Places/Brave devuelven
    paginas de listados ("Las 10 mejores...") en vez de negocios reales, y
    el guardrail de relevancia las rechaza correctamente (verificado en
    vivo: run pros-0a0da7c6cc, 27 candidatos -> 0 usables). Buscar cada
    categoria por separado es lo que arregla esto de raiz.

    Acotado a max_categories para no disparar sin limite el numero de
    queries (Brave es una fuente de pago, Places tiene presupuesto propio)
    — una descripcion con mas categorias que el tope simplemente usa las
    primeras N.
    """
    if not text or not text.strip():
        return []
    parts = [p.strip(" .") for p in _CATEGORY_SPLIT_RE.split(text.strip())]
    parts = [p for p in parts if p]
    return parts[:max_categories] if parts else [text.strip()]
