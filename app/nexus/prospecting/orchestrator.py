"""Prompt orchestration helpers for Nexus Sales prospecting."""

from __future__ import annotations

from typing import Any

from nexus.prompts import resolve_prompt_sync
from nexus.prospecting.autonomy import SalesAutonomousSystem
from nexus.prospecting.models import ProspectingBrief


class ProspectingPromptOrchestrator:
    """Refine user intent with guardrails and decide the discovery source plan."""

    def __init__(self, *, llm_client, brave_enabled: bool, places_enabled: bool) -> None:
        self._llm = llm_client
        self._brave_enabled = bool(brave_enabled)
        self._places_enabled = bool(places_enabled)
        self._autonomy = SalesAutonomousSystem()

    async def orchestrate(
        self,
        brief: ProspectingBrief,
        *,
        original_text: str = "",
    ) -> dict[str, Any]:
        orchestration_trace = self._autonomy.bootstrap(brief)
        guardian = await self._assess_brief_guardrails(brief, original_text=original_text)
        orchestration_trace = self._autonomy.update_agent(
            orchestration_trace,
            brief=brief,
            agent_id="brief_guardian",
            status="completed",
            summary=guardian["summary"],
            warnings=guardian["warnings"],
            guardrails_applied=guardian["guardrails_applied"],
            inputs={"original_text_present": bool(original_text.strip())},
            outputs={"geography_label": brief.geography_label, "represented_by": brief.represented_by},
        )
        refinement = await self._refine_with_guardrails(brief, original_text=original_text)
        refined_brief = self._apply_refinement(brief, refinement)
        source_strategy_notes = await self._explain_source_strategy(refined_brief)
        orchestration_trace = self._autonomy.update_agent(
            orchestration_trace,
            brief=refined_brief,
            agent_id="brief_refiner",
            status="completed",
            summary=(
                "Refino must/nice/exclude y tags sin tocar la intencion base."
                if refinement.get("_applied")
                else "No aplico refinado LLM; conservo el brief estructurado tal cual."
            ),
            warnings=refinement.get("warnings", []),
            guardrails_applied=[
                "No tocar vertical ni geografia.",
                "No tocar represented_by ni desired_count.",
            ],
            inputs={"target_description": brief.target_description, "must_have": brief.must_have},
            outputs={
                "target_description": refined_brief.target_description,
                "must_have": refined_brief.must_have,
                "nice_to_have": refined_brief.nice_to_have,
                "exclude": refined_brief.exclude,
                "crm_tags": refined_brief.crm_tags,
            },
        )
        source_plan = self.plan_sources(refined_brief, preferred_sources=refinement.get("preferred_sources"))
        orchestration_trace = self._autonomy.update_agent(
            orchestration_trace,
            brief=refined_brief,
            agent_id="source_strategist",
            status="completed",
            summary=source_strategy_notes.get("summary") or source_plan["summary"],
            warnings=source_strategy_notes.get("warnings", []),
            guardrails_applied=["Solo usar fuentes habilitadas y coherentes con la geografia."],
            inputs={"preferred_sources": refinement.get("preferred_sources", [])},
            outputs={
                "strategy": source_plan["strategy"],
                "sources": source_plan["sources"],
                "source_bias": source_strategy_notes.get("source_bias", ""),
            },
        )
        return {
            "brief": refined_brief.to_dict(),
            "orchestration": {
                "refinement_applied": bool(refinement.get("_applied")),
                "refinement_notes": refinement.get("notes", ""),
                "source_plan": source_plan,
                "autonomous_agents": self._autonomy.snapshot(orchestration_trace),
                "preserved_fields": [
                    "vertical",
                    "city",
                    "province",
                    "region",
                    "desired_count",
                    "minimum_score",
                    "represented_by",
                    "dry_run",
                ],
            },
        }

    def plan_sources(
        self,
        brief: ProspectingBrief,
        *,
        preferred_sources: list[str] | None = None,
    ) -> dict[str, Any]:
        geography_present = bool(brief.geography_label)
        places_available = self._places_enabled and geography_present

        if preferred_sources:
            ordered = [
                source
                for source in self._dedupe_strings(preferred_sources)
                if source in ("google_places", "brave")
            ]
        else:
            ordered = self._default_source_order(brief, geography_present)

        ordered = self._normalize_source_order(ordered, geography_present=geography_present)

        sources: list[dict[str, Any]] = []
        for source in ordered:
            if source != "google_places" or not places_available:
                continue
            role = "primary" if not sources else "secondary"
            sources.append(
                {
                    "name": source,
                    "role": role,
                    "enabled": True,
                    "reason": self._source_reason(source, brief, role),
                }
            )

        enrichment_sources: list[dict[str, Any]] = []
        if self._brave_enabled:
            enrichment_sources.append(
                {
                    "name": "brave",
                    "role": "enrichment",
                    "enabled": True,
                    "reason": "Brave se reserva para enriquecer candidatos ya descubiertos en Places.",
                }
            )

        if sources:
            strategy = "google_places_with_brave_enrichment" if enrichment_sources else "google_places_only"
            summary = sources[0]["reason"]
            if enrichment_sources:
                summary = f"{summary} Luego {enrichment_sources[0]['reason'].lower()}"
        else:
            strategy = "no_discovery_sources"
            summary = "No hay fuente de discovery util: sin geografia usable o sin Google Places habilitado."
            if enrichment_sources:
                summary = f"{summary} {enrichment_sources[0]['reason']}"
        return {
            "strategy": strategy,
            "summary": summary,
            "fallback_threshold": max(1, brief.desired_count),
            "sources": sources,
            "enrichment_sources": enrichment_sources,
        }

    async def _refine_with_guardrails(
        self,
        brief: ProspectingBrief,
        *,
        original_text: str = "",
    ) -> dict[str, Any]:
        base = {
            "target_description": brief.target_description,
            "must_have": list(brief.must_have),
            "nice_to_have": list(brief.nice_to_have),
            "exclude": list(brief.exclude),
            "crm_tags": list(brief.crm_tags),
            "preferred_sources": [],
            "notes": "",
            "_applied": False,
        }
        if not original_text.strip() or not getattr(self._llm, "enabled", False):
            return base

        schema_hint = {
            "target_description": "asesorias fiscales con email directo",
            "must_have": ["Email directo", "Web propia"],
            "nice_to_have": ["LinkedIn activo"],
            "exclude": ["franquicias", "directorios"],
            "crm_tags": ["prospeccion-nexus"],
            "preferred_sources": ["google_places", "brave"],
            "notes": "Mantengo geografia y marca; refino solo criterios de prospeccion.",
        }
        response = await self._llm.extract_json(
            system_prompt=resolve_prompt_sync("sales.prospecting.refine"),
            user_prompt=(
                f"Prompt original del usuario:\n{original_text}\n\n"
                f"Brief estructurado actual:\n{brief.to_dict()}\n\n"
                "Guardrails:\n"
                "- No inventes una ciudad ni una provincia nuevas.\n"
                "- No cambies la marca representada.\n"
                "- No cambies la vertical salvo error obvio; si dudas, conserva la original.\n"
                "- No reduzcas ni amplíes desired_count.\n"
                "- Excluye ruido comercial, directorios o targets incompatibles cuando sea seguro.\n"
                "- preferred_sources solo puede contener google_places y/o brave."
            ),
            schema_hint=schema_hint,
        )
        base.update(
            {
                "target_description": str(response.get("target_description") or base["target_description"]).strip(),
                "must_have": self._dedupe_strings(response.get("must_have") or base["must_have"]),
                "nice_to_have": self._dedupe_strings(response.get("nice_to_have") or base["nice_to_have"]),
                "exclude": self._dedupe_strings(response.get("exclude") or base["exclude"]),
                "crm_tags": self._dedupe_strings(response.get("crm_tags") or base["crm_tags"]),
                "preferred_sources": [
                    source
                    for source in self._dedupe_strings(response.get("preferred_sources") or [])
                    if source in {"google_places", "brave"}
                ],
                "notes": str(response.get("notes") or "").strip(),
                "warnings": self._dedupe_strings(response.get("warnings") or []),
                "_applied": True,
            }
        )
        return base

    async def _assess_brief_guardrails(self, brief: ProspectingBrief, *, original_text: str = "") -> dict[str, Any]:
        warnings: list[str] = []
        if not brief.geography_label:
            warnings.append("Falta geografia; Sales pedira ciudad, provincia o region antes del run.")
        if not brief.target_description.strip():
            warnings.append("El objetivo es generico; conviene concretar el tipo de lead buscado.")
        description = self._normalize_text(brief.target_description)
        if description:
            vertical_hints = {
                "restaurants": ("restaurante", "hosteleria", "cocina"),
                "asesoria": ("asesoria", "gestoria", "fiscal", "laboral"),
                "inmobiliaria": ("inmobiliaria", "agencia inmobiliaria", "pisos", "alquiler", "venta"),
                "public_administration": ("ayuntamiento", "administracion", "sede electronica", "concejal"),
            }
            expected = vertical_hints.get(brief.vertical, ())
            if expected and not any(hint in description for hint in expected):
                warnings.append(
                    "El target_description no parece encajar con la vertical declarada; se mantendra la vertical como verdad principal."
                )
        if brief.represented_by not in {"assets", "automato", "other"}:
            warnings.append("La marca representada no es estandar y se tratara como valor libre.")
        if original_text and len(original_text.strip()) < 12:
            warnings.append("El prompt original es muy corto; la precision comercial puede bajar.")
        summary = (
            "Guardrails preparados y briefing protegido antes de refinar."
            if warnings
            else "Guardrails preparados; el brief ya llega con base util para prospeccion."
        )
        if original_text.strip() and getattr(self._llm, "enabled", False):
            response = await self._llm.extract_json(
                system_prompt=resolve_prompt_sync("sales.prospecting.guardrails"),
                user_prompt=(
                    f"Prompt original:\n{original_text}\n\n"
                    f"Brief estructurado:\n{brief.to_dict()}\n\n"
                    "Devuelve riesgos y guardrails activos.\n"
                    "Si el brief ya contiene city y/o province, no emitas warnings diciendo que faltan."
                ),
                schema_hint={
                    "summary": "Guardrails preparados antes de ejecutar la prospeccion.",
                    "warnings": [],
                    "guardrails_applied": [],
                },
            )
            summary = str(response.get("summary") or summary).strip()
            warnings = self._sanitize_guardian_warnings(
                brief,
                [*warnings, *(response.get("warnings") or [])],
            )
            llm_guardrails = self._dedupe_strings(response.get("guardrails_applied") or [])
        else:
            llm_guardrails = []
        return {
            "summary": (
                summary
            ),
            "warnings": warnings,
            "guardrails_applied": self._dedupe_strings([
                "Preservar geografia declarada por el usuario.",
                "Preservar marca y volumen objetivo.",
                "No inventar targets ni contacto directo.",
                *llm_guardrails,
            ]),
        }

    def _sanitize_guardian_warnings(self, brief: ProspectingBrief, warnings: list[str]) -> list[str]:
        sanitized: list[str] = []
        city_present = bool(str(brief.city or "").strip())
        province_present = bool(str(brief.province or "").strip())
        geography_present = bool(brief.geography_label)

        for warning in self._dedupe_strings(warnings):
            lower = warning.lower()
            if geography_present and any(token in lower for token in (
                "falta geografia",
                "no especifica una ciudad",
                "no se especifica una ciudad",
                "sin ciudad",
                "falta ciudad",
                "no especifica ciudad",
            )):
                continue
            if city_present and any(token in lower for token in (
                "no especifica una ciudad",
                "no se especifica una ciudad",
                "sin ciudad",
                "falta ciudad",
                "no especifica ciudad",
            )):
                continue
            if province_present and any(token in lower for token in (
                "sin provincia",
                "falta provincia",
                "no especifica provincia",
                "no se especifica provincia",
            )):
                continue
            sanitized.append(warning)
        return sanitized

    async def _explain_source_strategy(self, brief: ProspectingBrief) -> dict[str, Any]:
        if not getattr(self._llm, "enabled", False):
            return {}
        response = await self._llm.extract_json(
            system_prompt=resolve_prompt_sync("sales.prospecting.source_strategy"),
            user_prompt=(
                f"Brief estructurado:\n{brief.to_dict()}\n\n"
                f"Brave habilitado: {self._brave_enabled}\n"
                f"Google Places habilitado: {self._places_enabled}\n"
                "Resume la estrategia: Places descubre y Brave solo enriquece si aplica."
            ),
            schema_hint={
                "summary": "Google Places descubre los candidatos y Brave se usa solo para enriquecerlos.",
                "source_bias": "google_places",
                "warnings": [],
            },
        )
        return {
            "summary": str(response.get("summary") or "").strip(),
            "source_bias": str(response.get("source_bias") or "").strip(),
            "warnings": self._dedupe_strings(response.get("warnings") or []),
        }

    def _apply_refinement(self, brief: ProspectingBrief, refinement: dict[str, Any]) -> ProspectingBrief:
        payload = brief.to_dict()
        payload["target_description"] = str(refinement.get("target_description") or payload["target_description"]).strip()
        payload["must_have"] = self._dedupe_strings(refinement.get("must_have") or payload["must_have"])
        payload["nice_to_have"] = self._dedupe_strings(refinement.get("nice_to_have") or payload["nice_to_have"])
        payload["exclude"] = self._dedupe_strings(refinement.get("exclude") or payload["exclude"])
        payload["crm_tags"] = self._dedupe_strings(refinement.get("crm_tags") or payload["crm_tags"])
        return ProspectingBrief(**payload)

    def _default_source_order(self, brief: ProspectingBrief, geography_present: bool) -> list[str]:
        if geography_present:
            return ["google_places", "brave"]
        return ["brave"]

    def _normalize_source_order(self, ordered: list[str], *, geography_present: bool) -> list[str]:
        deduped = [source for source in self._dedupe_strings(ordered) if source in {"google_places", "brave"}]
        if geography_present and self._places_enabled and "google_places" in deduped:
            remainder = [source for source in deduped if source != "google_places"]
            return ["google_places", *remainder]
        return deduped

    def _source_reason(self, source: str, brief: ProspectingBrief, role: str) -> str:
        if source == "google_places":
            if role == "primary":
                return "Google Places primero porque concentra negocio local y senales estructuradas mas fiables."
            return "Google Places como apoyo geolocalizado cuando falta cobertura o senal suficiente."
        if role == "primary":
            return "Brave primero solo porque no hay Places utilizable para este brief."
        return "Brave como fallback para ampliar cobertura cuando el origen principal se queda corto."

    @staticmethod
    def _dedupe_strings(values: Any) -> list[str]:
        items = values if isinstance(values, list) else str(values or "").split(",")
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            cleaned = str(item or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
        return result[:10]

    @staticmethod
    def _normalize_text(value: Any) -> str:
        import unicodedata

        raw = unicodedata.normalize("NFKD", str(value or ""))
        ascii_text = raw.encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_text.lower().split())
