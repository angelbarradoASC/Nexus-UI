"""
desktop/code_agent/evaluation.py
-------------------------------------
Conjunto de preguntas de prueba del agente de codigo (tests/eval/code_questions.json) y su
correccion automatica. Existe para dejar de evaluar por anecdota ("una pregunta, un intento"):
cada mejora del arnes (buscador, verificador de citas, prompts) se mide contra el mismo
conjunto, con los mismos modelos.

- Las respuestas esperadas son SIMBOLOS (fichero + funcion/metodo/constante), no numeros de
  linea: la linea se resuelve contra el indice actual, asi que sobrevive a editar el codigo.
- Dos metricas: `retrieval_report` (¿pone el buscador la funcion correcta entre las k primeras?,
  sin LLM) y `grade_answer` (¿cita la respuesta final un fichero y una linea correctos?).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .citations import citations
from .index import CodeIndex, Chunk

LINE_SLACK = 3


@dataclass(slots=True)
class Question:
    id: str
    question: str
    expect: list[dict[str, str]]
    split: str = "dev"


def load_questions(path: str | Path) -> list[Question]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Question(d["id"], d["question"], d["expect"], d.get("split", "dev")) for d in data]


def _matches(chunk: Chunk, expected: dict[str, str]) -> bool:
    if chunk.path != expected["path"]:
        return False
    return chunk.name == expected["symbol"] or expected["symbol"] in chunk.name.split(", ")


def resolve_symbols(index: CodeIndex, expect: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Cada simbolo esperado con su rango de lineas ACTUAL (o None si ya no existe)."""
    resolved = []
    for expected in expect:
        found = next((c for c in index._chunks if _matches(c, expected)), None)
        resolved.append({**expected, "start": found.start if found else None, "end": found.end if found else None})
    return resolved


@dataclass(slots=True)
class RetrievalResult:
    id: str
    split: str
    rank: int | None          # posicion (1-based) del primer simbolo esperado, o None
    top: list[str] = field(default_factory=list)


def retrieval_report(
    index: CodeIndex, questions: list[Question], k: int = 5, extra_terms: dict[str, list[str]] | None = None
) -> list[RetrievalResult]:
    """`extra_terms[id]`: palabras clave del LLM para esa pregunta (expansion), si se mide con ella."""
    results = []
    for question in questions:
        hits = index.search(question.question, k=k, per_file=2, extra_terms=(extra_terms or {}).get(question.id))
        rank = next(
            (i for i, hit in enumerate(hits, start=1) if any(_matches(hit.chunk, e) for e in question.expect)), None
        )
        results.append(RetrievalResult(question.id, question.split, rank, [f"{h.chunk.path}:{h.chunk.start} {h.chunk.name}" for h in hits]))
    return results


def summarize_retrieval(results: list[RetrievalResult], k: int = 5) -> dict[str, float]:
    def stats(rows: list[RetrievalResult]) -> dict[str, float]:
        if not rows:
            return {"n": 0, f"recall@{k}": 0.0, "mrr": 0.0}
        return {
            "n": len(rows),
            f"recall@{k}": sum(1 for r in rows if r.rank) / len(rows),
            "mrr": sum(1 / r.rank for r in rows if r.rank) / len(rows),
        }

    return {"all": stats(results), "dev": stats([r for r in results if r.split == "dev"]),
            "holdout": stats([r for r in results if r.split == "holdout"])}


def grade_answer(answer: str, resolved: list[dict[str, Any]]) -> dict[str, Any]:
    """Correcta si cita un fichero esperado con una linea dentro del rango del simbolo (±LINE_SLACK).
    'parcial' si acierta el fichero o nombra el simbolo pero no la linea."""
    cites = citations(answer)
    text = answer or ""
    for expected in resolved:
        if expected["start"] is None:
            continue
        for path, start, end in cites:
            if (path.endswith(expected["path"]) or expected["path"].endswith(path)) and (
                start <= expected["end"] + LINE_SLACK and end >= expected["start"] - LINE_SLACK
            ):
                return {"grade": "correcta", "why": f"cita {path}:{start} dentro de {expected['symbol']}"}
    for expected in resolved:
        symbol = expected["symbol"].split(".")[-1].split(", ")[0]
        file_hit = any(path.endswith(expected["path"]) or expected["path"].endswith(path) for path, _, _ in cites) or expected["path"] in text
        if file_hit or (symbol and symbol in text):
            return {"grade": "parcial", "why": f"menciona {expected['path'] if file_hit else symbol} sin una linea correcta"}
    return {"grade": "incorrecta", "why": "no cita ninguno de los sitios esperados"}
