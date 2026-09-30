"""
app/nexus/prospecting/campaign_decompose.py
------------------------------------------------
Descomposición + verificación de ida y vuelta para peticiones de la
Campaña en lenguaje natural. Deliberadamente distinto de
`sales.prospecting.interpret` (Sales) — pedido explícitamente así por el
usuario: la Campaña tiene su propio esquema, más pequeño, con un
mecanismo de verificación medible, no una opinión del LLM sobre sí mismo.

Flujo (diseñado con el usuario, no inventado):
1. El LLM principal (Groq) extrae {vertical, business_type, city,
   radius_km, clean_intent} del texto libre.
2. El LLM LOCAL (qwen3:8b, 192.168.68.150) recompone esos datos —sin ver
   el texto original— en una frase natural.
3. Se comparan embeddings (nomic-embed-text, mismo servidor) de
   clean_intent contra esa reconstrucción — similitud coseno, no
   solapamiento de palabras, para que "peluquerías" y "salones de
   belleza" cuenten como lo mismo.
4. Si la similitud < 0.95, el paso 1 se desvió de lo que el usuario pidió
   de verdad — se marca inconsistente en vez de seguir adelante callado.

Este módulo lo llaman dos sitios (misma función, sin duplicar lógica):
el endpoint nuevo para el cuadro de la pantalla de Campaña, y — cuando se
conecte— la skill de PEPO para poder pedirlo por chat.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nexus.prompts import resolve_prompt_sync
from nexus.prospecting.embeddings import LocalEmbeddingsClient, cosine_similarity
from nexus.prospecting.llm import LocalLLMClient
from nexus.prospecting.regulations import RegulationsRepository, build_regulations_block
from nexus.prospecting.sales_verticals import SalesVerticalsRepository

SIMILARITY_THRESHOLD = 0.95

_DECOMPOSE_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "set_campaign_query",
            "description": "Estructura una petición de cualificación de campaña en lenguaje natural.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vertical": {"type": "string", "description": "Slug del vertical, de la lista de verticales disponibles."},
                    "business_type": {"type": "string", "description": "Tipo de negocio tal como lo pidió el usuario, literal."},
                    "city": {"type": "string"},
                    "province": {"type": "string", "description": "Provincia, si el usuario la menciona o se infiere de la ciudad."},
                    "radius_km": {"type": "integer"},
                    "must_have": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Si el usuario pide explicitamente email o telefono de contacto, incluye 'email'/'telefono'; si no, [].",
                    },
                    "regulation_slug": {
                        "type": "string",
                        "description": (
                            "SOLO si el usuario pide empresas afectadas por una ley/normativa de "
                            "cumplimiento (ej. NIS2) en vez de un tipo de negocio literal — usa el "
                            "slug EXACTO de la lista de normativas del contexto. Si ninguna encaja, omite."
                        ),
                    },
                    "clean_intent": {
                        "type": "string",
                        "description": "La petición reescrita limpia y neutra, sin verbos de instrucción — solo el qué y el dónde.",
                    },
                },
                "required": ["business_type", "city", "clean_intent"],
            },
        },
    }
]


class CampaignDecomposer:
    """Descompone texto libre en una query estructurada de Campaña y la
    verifica de ida y vuelta contra el LLM local. Ver docstring del módulo."""

    def __init__(
        self,
        *,
        llm_router: Any,
        local_llm: LocalLLMClient,
        embeddings: LocalEmbeddingsClient,
        verticals: SalesVerticalsRepository,
        regulations: RegulationsRepository | None = None,
    ) -> None:
        self._llm_router = llm_router
        self._local_llm = local_llm
        self._embeddings = embeddings
        self._verticals = verticals
        self._regulations = regulations

    async def decompose_and_verify(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return {"status": "error", "error": "El texto está vacío."}

        query = await self._decompose(text)
        if query is None:
            return {"status": "error", "error": "No se pudo descomponer el texto — inténtalo de nuevo o reformúlalo."}

        reconstructed = await self._reconstruct(query)
        similarity: float | None = None
        consistent: bool | None = None
        note = ""

        if not self._local_llm.enabled or not self._embeddings.enabled:
            note = "Verificación no disponible (LLM local o embeddings deshabilitados) — descomposición sin comprobar."
        elif reconstructed is None:
            note = "El LLM local no respondió — descomposición sin comprobar."
        else:
            vec_clean = await self._embeddings.embed(query["clean_intent"])
            vec_reconstructed = await self._embeddings.embed(reconstructed)
            if vec_clean is None or vec_reconstructed is None:
                note = "No se pudo calcular la similitud — descomposición sin comprobar."
            else:
                similarity = cosine_similarity(vec_clean, vec_reconstructed)
                consistent = similarity >= SIMILARITY_THRESHOLD
                note = (
                    "El LLM entendió lo mismo que pediste."
                    if consistent
                    else "El LLM se desvió al descomponer — revisa antes de seguir."
                )

        return {
            "status": "ok",
            "original_text": text,
            "query": query,
            "reconstructed": reconstructed,
            "similarity": similarity,
            "consistent": consistent,
            "threshold": SIMILARITY_THRESHOLD,
            "note": note,
        }

    async def _decompose(self, text: str) -> dict[str, Any] | None:
        verticals_block = self._verticals_block()
        system_content = resolve_prompt_sync("campaign.decompose") + "\n\n" + verticals_block
        regulations_block = self._regulations_block()
        if regulations_block:
            system_content += "\n\n" + regulations_block
        try:
            response = await self._llm_router.call(
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": text},
                ],
                tools=_DECOMPOSE_TOOL,
                tool_choice={"type": "function", "function": {"name": "set_campaign_query"}},
                preferred_level=2,
                temperature=0.1,
                max_tokens=500,
                timeout=20.0,
            )
        except Exception:
            logger.exception("CampaignDecomposer | fallo llamando al LLM principal")
            return None
        if getattr(response, "error", None) or not response.tool_calls:
            return None
        try:
            args = json.loads(response.tool_calls[0]["function"]["arguments"] or "{}")
        except (KeyError, TypeError, json.JSONDecodeError):
            return None

        business_type = str(args.get("business_type") or "").strip()
        clean_intent = str(args.get("clean_intent") or "").strip()
        if not business_type or not clean_intent:
            return None

        vertical = self._verticals.resolve(args.get("vertical", ""), fallback_text=business_type).slug
        radius_km = args.get("radius_km")
        must_have = [str(v).strip() for v in (args.get("must_have") or []) if str(v).strip()]
        query = {
            "vertical": vertical,
            "business_type": business_type,
            "city": str(args.get("city") or "").strip(),
            "province": str(args.get("province") or "").strip(),
            "radius_km": int(radius_km) if isinstance(radius_km, (int, float)) else None,
            "must_have": must_have,
            "clean_intent": clean_intent,
        }
        self._ground_regulation(args, query)
        return query

    def _ground_regulation(self, args: dict[str, Any], query: dict[str, Any]) -> None:
        """Si el LLM identifico una normativa real (regulation_slug), sustituye
        business_type por los sectores REALES de esa normativa — nunca se
        confia en que el LLM los redacte bien (mismo guardarrail que
        _classify_grant_fit con las ayudas: lo que no esta en el catalogo
        real no se usa). Muta query in-place."""
        slug = str(args.get("regulation_slug") or "").strip()
        if not slug or self._regulations is None:
            return
        regulation = self._regulations.get(slug)
        if regulation is None or not regulation.activo:
            return
        query["regulation_slug"] = regulation.slug
        query["business_type"] = ", ".join(regulation.sectores)

    async def _reconstruct(self, query: dict[str, Any]) -> str | None:
        if not self._local_llm.enabled:
            return None
        payload = {k: v for k, v in query.items() if k != "clean_intent" and v not in (None, "")}
        response = await self._local_llm.complete(
            system_prompt=resolve_prompt_sync("campaign.reconstruct"),
            user_prompt=f"JSON:\n{json.dumps(payload, ensure_ascii=False)}",
            temperature=0.0,
            max_tokens=200,
        )
        cleaned = (response or "").strip().strip('"').strip()
        return cleaned or None

    def _verticals_block(self) -> str:
        active = self._verticals.list_active()
        if not active:
            return "VERTICALES DISPONIBLES: ninguna configurada. Usa 'custom'."
        lines = "\n".join(f"- {v.slug} ({v.nombre})" for v in active)
        return "VERTICALES DISPONIBLES (usa el slug que mejor encaje, o 'custom' si ninguno):\n" + lines

    def _regulations_block(self) -> str:
        if self._regulations is None:
            return ""
        active = self._regulations.list_active()
        if not active:
            return ""
        return (
            "NORMATIVAS DE CUMPLIMIENTO CONOCIDAS — si el usuario pide empresas afectadas por "
            "una ley/normativa de este catalogo, NUNCA copies el nombre de la ley como "
            "business_type — identifica el slug real en regulation_slug, el sistema "
            "construira business_type a partir de los sectores REALES. Si ninguna encaja, "
            "omite regulation_slug:\n" + build_regulations_block(active)
        )
