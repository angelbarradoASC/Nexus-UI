"""
desktop/obsidian/related.py
------------------------------
Notas de la boveda parecidas a un texto: para contrastar una nota nueva con lo que ya existe y proponer
"notas relacionadas". Busqueda por palabras (TF-IDF con peso extra en titulo, alias y etiquetas), sin LLM
ni embeddings: la boveda de una persona cabe en memoria y asi es instantaneo, local y repetible.
"""

from __future__ import annotations

import math
from collections import Counter

from desktop.code_agent.index import tokenize

from .graph import VaultGraph
from .notes import mask_code

TITLE_WEIGHT = 4.0
LABEL_WEIGHT = 3.0          # alias y etiquetas
MIN_SCORE = 1.0
MIN_MATCHED_TERMS = 2


def _index(graph: VaultGraph) -> tuple[dict[str, Counter], Counter, float]:
    cached = getattr(graph, "_related_cache", None)
    if cached is not None:
        return cached
    docs: dict[str, Counter] = {}
    df: Counter = Counter()
    for path, note in graph.notes.items():
        tf: Counter = Counter()
        for token in tokenize(note.title):
            tf[token] += TITLE_WEIGHT
        for label in [*note.aliases, *note.tags]:
            for token in tokenize(label):
                tf[token] += LABEL_WEIGHT
        for token in tokenize(mask_code(note.body)):
            tf[token] += 1.0
        docs[path] = tf
        df.update(tf.keys())
    avg = sum(sum(tf.values()) for tf in docs.values()) / max(len(docs), 1)
    graph._related_cache = (docs, df, avg)
    return graph._related_cache


def find_related(graph: VaultGraph, text: str, k: int = 3, exclude: set[str] | None = None) -> list[tuple[str, float]]:
    """Las `k` notas mas parecidas a `text` como (ruta, puntuacion), de mayor a menor. Solo devuelve las que
    comparten al menos MIN_MATCHED_TERMS terminos y superan MIN_SCORE: mejor ninguna que una al azar."""
    docs, df, avg = _index(graph)
    if not docs:
        return []
    query = Counter(tokenize(text))
    total = len(docs)
    scored: list[tuple[str, float]] = []
    for path, tf in docs.items():
        if exclude and path in exclude:
            continue
        matched = [t for t in query if t in tf]
        if len(matched) < MIN_MATCHED_TERMS:
            continue
        length_norm = 0.5 + 0.5 * (sum(tf.values()) / max(avg, 1.0))
        score = sum(
            math.log(1 + total / df[t]) * (1 + math.log(query[t])) * (tf[t] / (tf[t] + length_norm))
            for t in matched
        )
        if score >= MIN_SCORE:
            scored.append((path, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]
