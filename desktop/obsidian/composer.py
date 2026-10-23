"""
desktop/obsidian/composer.py
-------------------------------
Las dos tareas pequeñas que SI se le piden al LLM en el asistente de Obsidian:

1. `draft`: redactar (o dar formato a) el cuerpo de UNA nota. No escribe enlaces: los pone el codigo.
2. `contrast`: comparar la nota nueva con las 2-3 notas mas parecidas de la boveda y avisar de duplicados o
   contradicciones. Es el "apoyarse en el LLM para contrastar": una comparacion acotada, no una exploracion.

Todo lo que viaja al LLM pasa por `redact()`, y la respuesta se valida: los titulos que cite deben existir en la
lista que se le dio, y si el JSON no es valido se degrada con gracia (nunca se inventa un resultado).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from desktop.code_agent.workspace import redact
from nexus.prompts import resolve_prompt_sync
from nexus.utils.llm_json import parse_llm_json

from .notes import Note

logger = logging.getLogger("nexus.obsidian")

MAX_RELATED_CHARS = 2_500
MAX_TITLES_SENT = 150
MAX_TAGS_SENT = 60


@dataclass
class Draft:
    title: str
    body: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Contrast:
    available: bool = True                                          # False si el LLM no pudo hacer la comparacion
    duplicates: list[tuple[str, str]] = field(default_factory=list)       # (titulo, motivo)
    contradictions: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(self.duplicates or self.contradictions)


class NoteComposer:
    def __init__(self, llm_router: Any, *, preferred_level: int = 2) -> None:
        self._router = llm_router
        self._level = preferred_level

    async def _ask(self, system: str, user: str, *, max_tokens: int) -> dict | None:
        if self._router is None:
            return None
        try:
            response = await self._router.call(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                preferred_level=self._level, temperature=0.2, max_tokens=max_tokens, timeout=40.0,
            )
        except Exception:
            logger.exception("Obsidian: fallo llamando al LLM")
            return None
        if getattr(response, "error", None):
            logger.warning("Obsidian: el LLM devolvio un error (%s)", str(response.error)[:120])
            return None
        return parse_llm_json(response.content or "")

    async def draft(
        self, request: str, content: str, titles: list[str], tags: list[str],
    ) -> Draft | None:
        """None si el LLM no esta disponible o no devolvio una nota utilizable."""
        user = (
            f"PETICION DEL USUARIO:\n{redact(request)}\n\n"
            + (f"CONTENIDO DEL USUARIO:\n{redact(content)}\n\n" if content.strip() else "CONTENIDO DEL USUARIO: (ninguno)\n\n")
            + "TITULOS DE NOTAS EXISTENTES:\n" + ("\n".join(f"- {t}" for t in titles[:MAX_TITLES_SENT]) or "(ninguna)")
            + "\n\nETIQUETAS EXISTENTES: " + (", ".join(tags[:MAX_TAGS_SENT]) or "(ninguna)")
        )
        parsed = await self._ask(resolve_prompt_sync("pepo.obsidian_draft"), user, max_tokens=1600)
        if not parsed:
            return None
        body = str(parsed.get("body") or "").strip()
        if not body:
            return None
        raw_tags = parsed.get("tags")
        return Draft(
            title=str(parsed.get("title") or "").strip(),
            body=body,
            tags=[str(t) for t in raw_tags] if isinstance(raw_tags, list) else [],
        )

    async def contrast(self, new_title: str, new_body: str, related: list[Note]) -> Contrast:
        """Compara la nota nueva con las relacionadas. Sin relacionadas no hace falta llamar al LLM."""
        if not related:
            return Contrast()
        sections = "\n\n".join(
            f"### {note.title}\n{redact(note.body.strip())[:MAX_RELATED_CHARS]}" for note in related
        )
        user = (
            f"NOTA NUEVA «{new_title}»:\n{redact(new_body)[:MAX_RELATED_CHARS * 2]}\n\n"
            f"NOTAS EXISTENTES (usa estos titulos exactos):\n{sections}"
        )
        parsed = await self._ask(resolve_prompt_sync("pepo.obsidian_contrast"), user, max_tokens=700)
        if parsed is None:
            return Contrast(available=False)
        allowed = {note.title.lower(): note.title for note in related}

        def pairs(key: str) -> list[tuple[str, str]]:
            out: list[tuple[str, str]] = []
            for item in parsed.get(key) or []:
                if not isinstance(item, dict):
                    continue
                title = allowed.get(str(item.get("nota", "")).strip().lower())
                reason = str(item.get("motivo", "")).strip()
                if title and reason:                       # un titulo que no estaba en la lista se descarta
                    out.append((title, reason))
            return out

        return Contrast(duplicates=pairs("duplicates"), contradictions=pairs("contradictions"))

