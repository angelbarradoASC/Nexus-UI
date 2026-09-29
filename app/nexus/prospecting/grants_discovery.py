"""Mantiene el catalogo de ayudas fresco — sin esto, una ayuda sembrada hoy
queda obsoleta en silencio (mismo problema visto hoy con el .env
desincronizado del build empaquetado: un dato externo que cambia con el
tiempo y nadie vuelve a comprobar). Reutiliza los mismos clientes de
busqueda (Brave/DDG) y el mismo LocalLLMClient que ya usa
ProspectingAgentService — no crea infraestructura nueva, ni un tool de
busqueda propio.

Dos operaciones, pedidas explicitamente por el usuario:
- check_freshness(): para cada ayuda ya en catalogo, ¿sigue vigente?
- discover_new(): ¿hay programas nuevos no catalogados todavia?

Las ayudas descubiertas SIEMPRE entran en estado pendiente_revision, nunca
activas directamente — mismo principio que la cola de revision de leads:
lo que el sistema encuentra solo no se usa hasta que una persona lo
confirma (ver GrantsRepository.upsert_discovered).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nexus.prompts import resolve_prompt_sync
from nexus.prospecting.grants import GrantsRepository
from nexus.prospecting.llm import LocalLLMClient
from nexus.prospecting.sales_verticals import normalize_slug


class GrantsDiscoveryService:
    def __init__(
        self,
        *,
        grants: GrantsRepository,
        llm: LocalLLMClient,
        brave=None,
        ddg=None,
    ) -> None:
        self._grants = grants
        self._llm = llm
        self._brave = brave
        self._ddg = ddg

    @property
    def enabled(self) -> bool:
        return self._llm.enabled and (
            (self._brave is not None and self._brave.enabled)
            or (self._ddg is not None and self._ddg.enabled)
        )

    async def _search(self, query: str, run_id: str) -> list[dict[str, Any]]:
        """Brave primero si esta disponible (resultados mas fiables para
        paginas institucionales/convocatorias), si no cae a DDG."""
        if self._brave is not None and self._brave.enabled:
            payload = await self._brave.search(run_id=run_id, query=query, count=8)
            if payload.get("results"):
                return payload["results"]
        if self._ddg is not None and self._ddg.enabled:
            payload = await self._ddg.search(run_id=run_id, query=query, max_results=8)
            return payload.get("results", [])
        return []

    @staticmethod
    def _format_snippets(results: list[dict[str, Any]], *, with_url: bool = False) -> str:
        lines = []
        for r in results[:6]:
            title = r.get("title", "")
            desc = r.get("description", "")
            if with_url:
                lines.append(f"- {title}: {desc} ({r.get('url', '')})")
            else:
                lines.append(f"- {title}: {desc}")
        return "\n".join(lines)

    async def check_freshness(self) -> dict[str, Any]:
        """Comprueba vigencia real de cada ayuda activa/pendiente — marca
        'expirado' solo con evidencia real de busqueda, nunca por suposicion."""
        if not self.enabled:
            return {"status": "skipped", "reason": "LLM local o busqueda no disponibles"}

        checked: list[str] = []
        expired: list[str] = []
        candidates = [g for g in self._grants.list_all() if g.estado in ("activo", "pendiente_revision")]

        for grant in candidates:
            query = f"{grant.nombre} convocatoria 2026 vigente plazo solicitud"
            results = await self._search(query, run_id=f"grants-freshness-{grant.slug}")
            snippets = self._format_snippets(results)
            if not snippets:
                # Sin evidencia real no se cambia nada — se registra que se
                # intento comprobar, pero no se marca expirada sin datos.
                self._grants.mark_checked(grant.slug)
                checked.append(grant.slug)
                continue

            verdict = await self._llm.extract_json(
                system_prompt=resolve_prompt_sync("prospecting.grant_freshness"),
                user_prompt=f"Ayuda: {grant.nombre}\n\nResultados de busqueda real:\n{snippets}",
                schema_hint={"vigente": True, "vigente_hasta": "", "evidencia": ""},
            )
            checked.append(grant.slug)
            if verdict and verdict.get("vigente") is False:
                self._grants.set_estado(grant.slug, "expirado")
                self._grants.mark_checked(grant.slug, vigente_hasta=str(verdict.get("vigente_hasta") or ""))
                expired.append(grant.slug)
                logger.info(
                    "GrantsDiscovery | {} marcada como expirada | evidencia: {}",
                    grant.nombre, verdict.get("evidencia", ""),
                )
            else:
                nueva_fecha = str((verdict or {}).get("vigente_hasta") or "") or None
                self._grants.mark_checked(grant.slug, vigente_hasta=nueva_fecha)

        return {"status": "ok", "checked": checked, "expired": expired}

    async def discover_new(self, *, ambito: str, hints: list[str]) -> dict[str, Any]:
        """Busca programas NUEVOS no presentes en catalogo para las pistas
        de busqueda dadas (p.ej. 'nuevas ayudas ia empresas españa 2026').
        Los que encuentre entran como pendiente_revision — nunca activos
        directamente."""
        if not self.enabled:
            return {"status": "skipped", "reason": "LLM local o busqueda no disponibles"}

        discovered: list[str] = []
        existing_names = ", ".join(g.nombre for g in self._grants.list_all()) or "(catalogo vacio)"

        for hint in hints:
            results = await self._search(hint, run_id=f"grants-discovery-{ambito}")
            snippets = self._format_snippets(results, with_url=True)
            if not snippets:
                continue

            extraction = await self._llm.extract_json(
                system_prompt=resolve_prompt_sync("prospecting.grant_discovery"),
                user_prompt=(
                    f"Busqueda: {hint}\n\nResultados reales:\n{snippets}\n\n"
                    f"Ayudas YA en catalogo (no las repitas, ni con nombre ligeramente "
                    f"distinto): {existing_names}"
                ),
                schema_hint={"programas": [{
                    "nombre": "", "criterios": "", "min_employees": None,
                    "max_employees": None, "importe_desc": "", "url": "", "vigente_hasta": "",
                }]},
            )
            for programa in (extraction or {}).get("programas") or []:
                nombre = str(programa.get("nombre") or "").strip()
                if not nombre or self._grants.find_by_name(nombre):
                    continue
                slug = normalize_slug(nombre) or normalize_slug(hint)
                if not slug or self._grants.get(slug):
                    continue
                grant = self._grants.upsert_discovered(
                    slug=slug,
                    nombre=nombre,
                    ambito=ambito,
                    min_employees=programa.get("min_employees"),
                    max_employees=programa.get("max_employees"),
                    importe_desc=str(programa.get("importe_desc") or ""),
                    criterios=str(programa.get("criterios") or ""),
                    url=str(programa.get("url") or ""),
                    vigente_hasta=str(programa.get("vigente_hasta") or ""),
                )
                discovered.append(grant.slug)
                logger.info("GrantsDiscovery | nueva ayuda pendiente de revision: {}", grant.nombre)

        return {"status": "ok", "discovered": discovered}
