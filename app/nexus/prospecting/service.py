"""Generalized local-first prospecting service for Nexus Sales."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from loguru import logger as _logger

from nexus.connectors.crm import AssetsCRMConnector
from nexus.prompts import resolve_prompt_sync
from nexus.prospecting.autonomy import SalesAutonomousSystem
from nexus.prospecting.brave import BraveSearchClient, BraveSearchSettings
from nexus.prospecting.ddg import DdgSearchClient, DdgSearchSettings
from nexus.prospecting.extractors import WebProspectExtractor
from nexus.prospecting.google_places import GooglePlacesClient, GooglePlacesSettings
from nexus.prospecting.llm import LocalLLMClient, LocalLLMSettings
from nexus.api.schemas.prospecting import ProspectingRunRequest
from nexus.prospecting.models import KNOWN_VERTICALS, ProspectingBrief, default_tags_for_vertical, normalize_vertical
from nexus.prospecting.orchestrator import ProspectingPromptOrchestrator
from nexus.prospecting.api_budget import BudgetExceededError, PlacesApiBudget
from nexus.prospecting.filters import BLOCKED_HINT_PREFIXES, VERTICAL_BLOCKLIST
from nexus.utils.text import normalize_text as _normalize_text
from nexus.prospecting.repository import ProspectingRepository
from nexus.prospecting.scoring import ProspectScorer
from nexus.prospecting.validators import DomainValidator, EmailValidator, MXValidator


class ProspectingAgentService:
    """Run local-first prospecting with Places discovery, Brave enrichment, and CRM dedupe."""

    def __init__(
        self,
        *,
        cfg,
        repository: ProspectingRepository | None = None,
        connector: AssetsCRMConnector | None = None,
        llm_client: LocalLLMClient | None = None,
        brave_client: BraveSearchClient | None = None,
        ddg_client: DdgSearchClient | None = None,
        places_client: GooglePlacesClient | None = None,
        extractor: WebProspectExtractor | None = None,
        email_validator: EmailValidator | None = None,
        domain_validator: DomainValidator | None = None,
        mx_validator: MXValidator | None = None,
        scorer: ProspectScorer | None = None,
    ) -> None:
        self._cfg = cfg
        self._repository = repository or ProspectingRepository(cfg.prospecting_data_dir)
        self._connector = connector or AssetsCRMConnector(
            base_url=cfg.assets_crm_base_url,
            username=cfg.assets_crm_username,
            password=cfg.assets_crm_password,
        )
        self._llm = llm_client or LocalLLMClient(
            settings=LocalLLMSettings(
                base_url=getattr(cfg, "local_llm_base_url", None) or cfg.l0_url,
                model=getattr(cfg, "local_llm_model", "") or cfg.l0_model,
                provider=getattr(cfg, "local_llm_provider", "openai_compatible"),
                timeout=float(getattr(cfg, "local_llm_timeout", 60)),
                retries=int(getattr(cfg, "local_llm_retries", 2)),
                enabled=bool(getattr(cfg, "local_llm_enabled", False) or cfg.l0_url),
            ),
            api_key=getattr(cfg, "local_llm_api_key", "") or cfg.l0_key,
        )
        self._brave = brave_client or BraveSearchClient(
            settings=BraveSearchSettings(
                api_key=getattr(cfg, "brave_search_api_key", None),
                enabled=bool(getattr(cfg, "brave_search_enabled", False)),
                rate_limit_seconds=float(getattr(cfg, "brave_search_rate_limit", 1.0)),
                timeout=float(getattr(cfg, "prospecting_http_timeout_seconds", 20)),
            ),
            repository=self._repository,
        )
        self._ddg = ddg_client or DdgSearchClient(
            settings=DdgSearchSettings(
                enabled=True,
                rate_limit_seconds=1.5,
                timeout=float(getattr(cfg, "prospecting_http_timeout_seconds", 20)),
            ),
            repository=self._repository,
        )
        self._places = places_client or GooglePlacesClient(
            settings=GooglePlacesSettings(
                api_key=getattr(cfg, "google_places_api_key", None),
                enabled=bool(getattr(cfg, "google_places_enabled", False)),
                rate_limit_seconds=float(getattr(cfg, "google_places_rate_limit", 0.5)),
                timeout=float(getattr(cfg, "prospecting_http_timeout_seconds", 20)),
                max_results_per_query=int(getattr(cfg, "google_places_max_results_per_query", 20)),
            ),
        )
        self._extractor = extractor or WebProspectExtractor(
            timeout_seconds=float(cfg.prospecting_http_timeout_seconds),
            user_agent=cfg.prospecting_user_agent,
            max_pages_per_site=int(cfg.prospecting_max_pages_per_site),
        )
        self._email_validator = email_validator or EmailValidator()
        self._domain_validator = domain_validator or DomainValidator()
        self._mx_validator = mx_validator or MXValidator()
        self._scorer = scorer or ProspectScorer()
        self._budget = PlacesApiBudget(cfg.prospecting_data_dir)
        self._orchestrator = ProspectingPromptOrchestrator(
            llm_client=self._llm,
            brave_enabled=self._brave.enabled,
            places_enabled=self._places.enabled,
            ddg_enabled=self._ddg.enabled,
        )
        self._autonomy = SalesAutonomousSystem()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._verticals_cache: tuple[float, list[dict[str, Any]]] | None = None

    # ── Verticales reales del CRM (sin hardcodear) ──────────────────────────────

    _VERTICALS_CACHE_TTL_SECONDS = 600  # 10 min — evita golpear el CRM en cada mensaje

    async def list_crm_verticals(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Verticales que existen AHORA MISMO en el CRM, extraidas de los leads
        ya registrados ("Vertical: X" en las notas) — nunca una lista fija en
        codigo. El LLM de interpretacion recibe esta lista real para clasificar,
        en vez de un catalogo hardcodeado que se queda desactualizado.
        """
        now = time.monotonic()
        if not force_refresh and self._verticals_cache is not None:
            cached_at, cached = self._verticals_cache
            if now - cached_at < self._VERTICALS_CACHE_TTL_SECONDS:
                return cached

        if not self._connector.configured:
            return self._verticals_cache[1] if self._verticals_cache else []

        try:
            data = await self._connector.list_pipeline()
        except Exception:
            _logger.exception("list_crm_verticals | fallo consultando el CRM")
            return self._verticals_cache[1] if self._verticals_cache else []

        counts: dict[str, int] = {}
        for company in data.get("companies", []):
            match = re.search(r"Vertical:\s*([^\n]+)", company.get("notes") or "")
            if match:
                slug = match.group(1).strip()
                if slug:
                    counts[slug] = counts.get(slug, 0) + 1

        verticals = [
            {"slug": slug, "count": count}
            for slug, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
        self._verticals_cache = (now, verticals)
        return verticals

    # ── Logging ──────────────────────────────────────────────────────────────

    @staticmethod
    def _log(run: dict[str, Any], message: str, level: str = "info", *, hito: bool = False, **extra: Any) -> None:
        """Append a structured event to run['logs'] and emit to loguru.

        hito=True ademas manda el mensaje a hitos.log (arranque/fin de run,
        no el ruido de cada query intermedia).
        """
        event: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "msg": message,
        }
        if extra:
            event["data"] = extra
        run.setdefault("logs", []).append(event)
        full_message = f"[{run.get('run_id', '?')}] {message}" + (f" | {extra}" if extra else "")
        if hito:
            from utils.logger import hito as _hito
            _hito(full_message)
        log_fn = getattr(_logger, level, _logger.info)
        log_fn(full_message)

    async def run(self, payload: ProspectingRunRequest) -> dict[str, Any]:
        brief = self._normalize_brief(payload)
        source_plan = self._orchestrator.plan_sources(brief)
        run_id = f"pros-{uuid4().hex[:10]}"
        run = self._new_run(run_id, brief, source_plan=source_plan)
        await self._repository.append_run(run)

        if brief.async_mode:
            self._tasks[run_id] = asyncio.create_task(self._execute_run(run_id, brief))
            return self._run_summary(run)

        timeout_seconds = float(max(getattr(brief, "max_run_minutes", 10), 2)) * 60.0
        try:
            run = await asyncio.wait_for(self._execute_run(run_id, brief), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            saved = await self._repository.get_run(run_id)
            if saved:
                saved["status"] = "timeout"
                saved["error"] = f"Run timeout (>{int(timeout_seconds//60)} min) — demasiadas webs lentas o DDG bloqueado"
                saved["finished_at"] = datetime.now(timezone.utc).isoformat()
                runs = await self._repository.load_runs()
                for i, r in enumerate(runs):
                    if r.get("run_id") == run_id:
                        runs[i] = saved
                        break
                await self._repository.save_runs(runs)
                run = saved
            else:
                run = self._new_run(run_id, brief)
                run["status"] = "timeout"
        return self._run_summary(run)

    async def orchestrate_brief(self, payload: dict[str, Any], *, original_text: str = "") -> dict[str, Any]:
        # _normalize_brief espera un objeto con atributos (ProspectingRunRequest), no un
        # dict — pasarle el dict tal cual rompia con AttributeError y el refinamiento/
        # guardrails se saltaban en silencio (capturado como excepcion generica arriba).
        known_fields = ProspectingRunRequest.model_fields
        request = ProspectingRunRequest(**{k: v for k, v in payload.items() if k in known_fields})
        brief = self._normalize_brief(request)
        return await self._orchestrator.orchestrate(brief, original_text=original_text)

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        run = await self._repository.get_run(run_id)
        if run is None:
            return {"status": "not_found", "run_id": run_id}
        brief = self._normalize_brief(run.get("brief") or {})
        resumed = await self._execute_run(run_id, brief, reset=True, resumed_from=run.get("status"))
        return self._run_summary(resumed)

    def get_budget(self) -> dict:
        """Return current month's API budget status (synchronous snapshot)."""
        return self._budget.status()

    async def get_run(self, run_id: str) -> dict[str, Any]:
        run = await self._repository.get_run(run_id)
        if run is None:
            return {"status": "not_found", "run_id": run_id}
        return run

    async def quick_probe(self, *, city: str, vertical: str) -> dict:
        """3-result DDG probe to check if a city/vertical combination has real results."""
        vertical_label = vertical.replace("_", " ")
        query = f"{vertical_label} {city} contacto email"
        try:
            payload = await self._ddg.search(run_id="", query=query, max_results=5)
            results = payload.get("results", [])
            real = [r for r in results if not self._ddg.is_directory_domain(r.get("url", ""))]
            if len(real) >= 2:
                quality = "ok"
            elif real:
                quality = "sparse"
            else:
                quality = "empty"
            return {"hits": len(real), "quality": quality}
        except Exception:
            return {"hits": 0, "quality": "unknown"}

    async def list_results(
        self,
        *,
        run_id: str | None = None,
        min_score: int | None = None,
        crm_state: str | None = None,
        vertical: str | None = None,
    ) -> dict[str, Any]:
        runs = await self._repository.load_runs()
        results: list[dict[str, Any]] = []
        for run in runs:
            if run_id and run.get("run_id") != run_id:
                continue
            if vertical and (run.get("brief") or {}).get("vertical") != vertical:
                continue
            results.extend(run.get("results", []))
        if min_score is not None:
            results = [item for item in results if int(item.get("score", 0)) >= min_score]
        if crm_state:
            results = [item for item in results if str(item.get("crm_state", "")).lower() == crm_state.lower()]
        return {"status": "success", "results": results}

    async def list_discarded(self, *, run_id: str | None = None, vertical: str | None = None) -> dict[str, Any]:
        runs = await self._repository.load_runs()
        discarded: list[dict[str, Any]] = []
        for run in runs:
            if run_id and run.get("run_id") != run_id:
                continue
            if vertical and (run.get("brief") or {}).get("vertical") != vertical:
                continue
            discarded.extend(run.get("discarded", []))
        return {"status": "success", "discarded": discarded}

    async def push_result_to_crm(self, result_id: str, *, dry_run: bool = True) -> dict[str, Any]:
        runs = await self._repository.load_runs()
        located = self._locate_result(runs, result_id)
        if located is None:
            return {"status": "not_found", "result_id": result_id}
        _, run, result = located
        response = await self._push_single_result(result, run.get("brief") or {}, dry_run=dry_run)
        if response["status"] == "accepted" and not dry_run:
            result["crm_state"] = "created"
            result["crm_sync"] = {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "company_id": response.get("company_id"),
                "dry_run": False,
            }
            await self._repository.save_runs(runs)
        return response

    async def push_valid_to_crm(self, run_id: str, *, dry_run: bool = True) -> dict[str, Any]:
        runs = await self._repository.load_runs()
        run = next((item for item in runs if item.get("run_id") == run_id), None)
        if run is None:
            return {"status": "not_found", "run_id": run_id}
        brief = run.get("brief") or {}
        pushed: list[dict[str, Any]] = []
        run["status"] = "pushing_to_crm"
        for result in run.get("results", []):
            if not result.get("crm_ready"):
                continue
            response = await self._push_single_result(result, brief, dry_run=dry_run)
            if response["status"] == "accepted" and not dry_run:
                result["crm_state"] = "created"
                result["crm_sync"] = {
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "company_id": response.get("company_id"),
                    "dry_run": False,
                }
            pushed.append(response)
        run["status"] = "completed"
        if not dry_run:
            run["summary"]["pushed_to_crm"] = len([item for item in pushed if item.get("status") == "accepted"])
            await self._repository.save_runs(runs)
        return {
            "status": "accepted",
            "run_id": run_id,
            "dry_run": dry_run,
            "pushed_count": len(pushed),
            "results": pushed,
        }

    def generate_queries(self, brief: ProspectingBrief) -> list[str]:
        geography = brief.geography_label or brief.target_description or "España"
        if brief.vertical == "restaurants":
            base = [
                f"mejores restaurantes {geography} email contacto",
                f"restaurante alta cocina {geography} reservas contacto",
                f"restaurante eventos empresa {geography} contacto",
                f"restaurante gourmet {geography} reservas email",
                f"restaurante {geography} cenas empresa",
                f"restaurante {geography} terraza reservas",
                f"restaurante {geography} carta degustacion reservas",
            ]
        elif brief.vertical == "salud":
            base = [
                f"clinica dental {geography} contacto",
                f"dentista {geography} email telefono",
                f"odontologo {geography} contacto",
                f"clinica odontologica {geography} contacto",
                f"salud dental {geography} contacto",
            ]
        elif brief.vertical == "salud":
            signals = ("clinica", "clínica", "dentista", "odont", "salud", "implante", "ortodon", "estetica dental")
            relevant = any(token in text for token in signals)
            reason = "salud/dental con seÃ±ales de clinica o consulta" if relevant else "no parece clinica dental"
        elif brief.vertical == "public_administration":
            focus = brief.target_description or "ayuntamiento administración electrónica contacto"
            base = [
                f"ayuntamiento {geography} contacto tecnología",
                f"sede electrónica {geography} ayuntamiento contacto",
                f"concejalía nuevas tecnologías {geography}",
                f"secretaría ayuntamiento {geography} contacto",
                f"{focus} {geography}",
            ]
        elif brief.vertical == "inmobiliaria":
            geo = geography or "EspaÃ±a"
            exclusions = (
                "-site:idealista.com -site:fotocasa.es -site:pisos.com "
                "-site:habitaclia.com -site:yaencontre.com -site:indomio.es "
                "-site:globaliza.com -site:trovimap.com"
            )
            base = [
                f"\"inmobiliaria\" \"{geo}\" contacto {exclusions}",
                f"\"agencia inmobiliaria\" \"{geo}\" email telefono {exclusions}",
                f"intitle:inmobiliaria \"{geo}\" nosotros contacto {exclusions}",
                f"\"inmobiliaria\" \"{geo}\" \"aviso legal\" {exclusions}",
                f"\"inmobiliaria\" \"{geo}\" \"equipo\" {exclusions}",
            ]
        elif brief.industrial_zone:
            zone = brief.industrial_zone
            prov = brief.province or brief.city or geography
            desc = brief.target_description or "empresa"
            base = [
                f"empresas \"{zone}\" {prov} contacto email",
                f"\"{zone}\" {prov} empresa teléfono email",
                f"site:axesor.es \"{zone}\" {prov}",
                f"site:einforma.com \"{zone}\" {prov}",
                f"\"{zone}\" {prov} directorio empresas",
                f"{desc} polígono industrial \"{zone}\" {prov}",
            ]
        else:
            base = [
                f"{brief.target_description} {geography} contacto",
                f"{brief.target_description} {geography} email teléfono",
            ]

        # Employee range hint in queries
        if brief.min_employees or brief.max_employees:
            emp_label = ""
            if brief.min_employees and brief.max_employees:
                emp_label = f"{brief.min_employees}-{brief.max_employees} empleados"
            elif brief.min_employees:
                emp_label = f"más de {brief.min_employees} empleados"
            else:
                emp_label = f"hasta {brief.max_employees} empleados"
            geo = brief.industrial_zone or geography
            base.append(f"{brief.target_description or 'empresa'} {geo} {emp_label}")

        for token in brief.must_have[:3]:
            base.append(f"{brief.target_description or brief.vertical} {geography} {token}")

        unique: list[str] = []
        seen: set[str] = set()
        for query in base:
            cleaned = " ".join(query.split()).strip()
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                unique.append(cleaned)
        return unique[:10]

    async def _execute_run(
        self,
        run_id: str,
        brief: ProspectingBrief,
        *,
        reset: bool = False,
        resumed_from: str | None = None,
    ) -> dict[str, Any]:
        runs = await self._repository.load_runs()
        run = next(item for item in runs if item.get("run_id") == run_id)
        if reset:
            run["results"] = []
            run["discarded"] = []
            run["summary"] = self._empty_summary()
            run["error"] = None
            if resumed_from:
                run["resumed_from"] = resumed_from
        run["started_at"] = run.get("started_at") or datetime.now(timezone.utc).isoformat()
        run.setdefault("logs", [])

        try:
            run["status"] = "searching"
            geography = brief.geography_label or f"{brief.city} {brief.province}".strip()
            self._log(run, "Run iniciado", hito=True, vertical=brief.vertical, geography=geography, desired=brief.desired_count, dry_run=brief.dry_run)

            source_plan = (run.get("orchestration") or {}).get("source_plan") or self._orchestrator.plan_sources(brief)
            self._log(run, "Plan de orquestacion resuelto", strategy=source_plan.get("strategy"), summary=source_plan.get("summary"))
            self._update_autonomous_agent(
                run,
                brief,
                agent_id="query_architect",
                status="running",
                summary="Preparando queries base y expansiones controladas antes de buscar.",
                guardrails_applied=[
                    "No repetir queries triviales.",
                    "Priorizar contacto directo y web propia.",
                ],
                inputs={"target_description": brief.target_description, "must_have": brief.must_have},
            )
            self._update_autonomous_agent(
                run,
                brief,
                agent_id="search_executor",
                status="running",
                summary="Ejecutando fuentes segun la estrategia aprobada por Source Strategist.",
                guardrails_applied=["Respetar el orden de fuentes y el fallback threshold."],
                inputs={"source_plan": source_plan},
            )
            raw_hits: list[dict[str, Any]] = []
            run["queries"] = []
            used_sources: list[str] = []

            # ── Agentic multi-round discovery ────────────────────────────────
            rounds = self._orchestrator.plan_rounds(brief)
            quality_threshold = max(3, brief.desired_count // 4)
            queried_sources: set[str] = set()

            for round_cfg in rounds:
                round_label = round_cfg["label"]
                new_sources = round_cfg["new_sources"]
                self._log(run, f"Ronda {round_cfg['round']}: {round_label}", sources=new_sources)

                round_hits: list[dict[str, Any]] = []
                for source_name in new_sources:
                    if source_name in queried_sources:
                        continue
                    if source_name == "ddg":
                        hits, queries = await self._discover_with_ddg(run_id, run, brief)
                    elif source_name == "google_places":
                        batch = await self._discover_with_places(run, brief, geography=geography)
                        if batch is None:
                            await self._repository.update_run(run_id, lambda r: {**r, **run})
                            return run
                        hits, queries = batch
                    elif source_name == "brave":
                        hits, queries = await self._discover_with_brave(run_id, run, brief)
                    else:
                        continue
                    queried_sources.add(source_name)
                    if hits:
                        if source_name not in used_sources:
                            used_sources.append(source_name)
                        round_hits.extend(hits)
                    run["queries"].extend(q for q in queries if q not in run["queries"])

                raw_hits = self._merge_raw_hits(raw_hits, round_hits)
                real_count = self._count_real_domains(raw_hits)
                self._log(
                    run,
                    f"Ronda {round_cfg['round']} terminada: {real_count} dominios reales acumulados (umbral={quality_threshold})",
                    new_hits=len(round_hits),
                    total_hits=len(raw_hits),
                )
                if real_count >= quality_threshold:
                    self._log(run, f"Umbral alcanzado tras ronda {round_cfg['round']} — sin escalada adicional")
                    break

            if used_sources:
                run["discovery_source"] = "+".join(dict.fromkeys(used_sources))
            search_audit = await self._audit_search_phase(
                brief,
                queries=run["queries"],
                used_sources=used_sources,
                raw_hits=len(raw_hits),
            )
            self._update_autonomous_agent(
                run,
                brief,
                agent_id="query_architect",
                status="completed",
                summary=f"Arquitectura de busqueda resuelta con {len(run['queries'])} queries utiles.",
                warnings=[] if run["queries"] else ["No se genero ninguna consulta util de discovery."],
                guardrails_applied=[
                    "No expandir sin control el espacio de busqueda.",
                    "Conservar el foco comercial del brief.",
                ],
                outputs={"queries": run["queries"][:8]},
            )
            self._update_autonomous_agent(
                run,
                brief,
                agent_id="search_executor",
                status="completed",
                summary=(
                    search_audit.get("summary")
                    or (
                    f"Busqueda ejecutada en {', '.join(used_sources)} con {len(raw_hits)} hits brutos."
                    if used_sources
                    else "No habia fuentes habilitadas o no devolvieron resultados."
                    )
                ),
                warnings=self._dedupe_list(
                    [
                        *(search_audit.get("warnings") or []),
                        *([] if raw_hits else ["La fase de discovery no ha devuelto candidatos brutos."]),
                    ]
                ),
                guardrails_applied=["Solo se usan hits trazables por Places; Brave no descubre leads."],
                outputs={
                    "used_sources": used_sources,
                    "raw_hits": len(raw_hits),
                    "next_adjustment": search_audit.get("next_adjustment", ""),
                },
            )

            run["summary"]["raw_candidates"] = len(raw_hits)

            run["status"] = "extracting"
            candidates = self._dedupe_candidates(raw_hits)
            self._log(run, f"{len(candidates)} candidatos únicos tras deduplicación")

            self._update_autonomous_agent(
                run,
                brief,
                agent_id="candidate_qualifier",
                status="running",
                summary="Extrayendo, validando y puntuando candidatos antes de aceptarlos.",
                guardrails_applied=[
                    "Ser conservador con official_website y contacto directo.",
                    "Descartar webs sin evidencia minima.",
                ],
                inputs={"candidate_count": len(candidates), "minimum_score": brief.minimum_score},
            )
            for candidate in candidates:
                cname = candidate.get("title") or candidate.get("name") or candidate.get("url", "?")
                self._log(run, f"Procesando: {cname[:60]}", url=candidate.get("url", ""))
                extracted = await self._extract_candidate(run_id, run, candidate, brief)
                if not extracted.get("website"):
                    extracted["status"] = "discarded"
                    extracted["discard_reason"] = "no_website"
                    extracted["discard_reason_label"] = self._humanize_reason("no_website")
                    run["discarded"].append(extracted)
                    run["summary"]["discarded"] += 1
                    self._log(run, f"Descartado sin web: {cname[:50]}", level="warning")
                    continue

                strict_failures = self._evaluate_candidate_guardrails(candidate, extracted, brief)
                if strict_failures:
                    extracted["status"] = "discarded"
                    extracted["strict_guardrail_failures"] = strict_failures
                    extracted["discard_reason"] = strict_failures[0]
                    extracted["discard_reason_label"] = self._humanize_reason(strict_failures[0])
                    run["discarded"].append(extracted)
                    run["summary"]["discarded"] += 1
                    self._log(
                        run,
                        f"Descartado por guardrail: {extracted.get('name', cname)[:50]}",
                        level="warning",
                        reason=strict_failures[0],
                        reasons=strict_failures,
                    )
                    continue

                run["status"] = "validating"
                domain_validation = await self._domain_validator.validate(extracted.get("domain", ""))
                mx_validation = await self._mx_validator.validate(extracted.get("domain", ""))
                email_validation = self._email_validator.validate(extracted.get("email", ""))

                extracted.update(domain_validation)
                extracted.update(mx_validation)
                extracted["email_validation"] = email_validation

                duplicate = await self._find_duplicate(
                    extracted.get("name", ""),
                    extracted.get("domain", ""),
                    extracted.get("email", ""),
                    extracted.get("phone", ""),
                )
                extracted["crm_duplicate"] = duplicate
                extracted["crm_state"] = "duplicate" if duplicate else "pending"
                if duplicate:
                    self._log(run, f"Duplicado CRM: {cname[:50]}", level="warning")

                run["status"] = "scoring"
                score_payload = self._scorer.score(extracted, vertical=brief.vertical, minimum_score=brief.minimum_score)
                extracted.update(score_payload)
                extracted["crm_blockers"] = self._crm_blockers(extracted, brief)
                extracted["crm_ready"] = not extracted["crm_blockers"] and bool(extracted.get("accepted"))
                extracted["review_status"] = "ready_for_crm" if extracted["crm_ready"] else "needs_review"
                score = extracted.get("score", 0)
                priority = extracted.get("priority", "-")
                if extracted.get("crm_duplicate"):
                    run["summary"]["duplicates"] += 1
                if extracted.get("crm_ready"):
                    run["summary"]["crm_ready"] += 1

                if extracted["accepted"]:
                    run["results"].append(extracted)
                    run["summary"]["usable_results"] += 1
                    self._log(
                        run,
                        f"Aceptado: {extracted.get('name', cname)[:50]} | score={score} | {priority} | email={bool(extracted.get('email'))} | phone={bool(extracted.get('phone'))}",
                        crm_ready=extracted.get("crm_ready"),
                    )
                else:
                    extracted["status"] = "discarded"
                    run["discarded"].append(extracted)
                    run["summary"]["discarded"] += 1
                    extracted["discard_reason_label"] = self._humanize_reason(extracted.get("discard_reason"))
                    self._log(run, f"Descartado: {extracted.get('name', cname)[:50]} | score={score} | motivo={extracted.get('discard_reason','baja_puntuacion')}", level="warning")

                if len(run["results"]) >= brief.desired_count:
                    self._log(run, f"Objetivo alcanzado: {len(run['results'])} resultados")
                    break

            # LinkedIn pass: enrich accepted results with real snippet-based contacts
            await self._linkedin_pass(run["results"], brief)

            self._update_autonomous_agent(
                run,
                brief,
                agent_id="candidate_qualifier",
                status="completed",
                summary=(
                    f"Calificacion cerrada: {len(run['results'])} aceptados, "
                    f"{len(run['discarded'])} descartados y {run['summary']['duplicates']} duplicados."
                ),
                warnings=[] if run["results"] else ["No ha quedado ningun lead util tras la calificacion."],
                guardrails_applied=[
                    "Mantener scoring minimo configurado.",
                    "No aceptar leads sin evidencia usable.",
                ],
                outputs={
                    "accepted": len(run["results"]),
                    "discarded": len(run["discarded"]),
                    "duplicates": run["summary"]["duplicates"],
                },
            )
            crm_ready = [
                item
                for item in run["results"]
                if item.get("crm_ready")
            ]
            crm_handoff = await self._summarize_crm_packager(
                brief,
                crm_ready_count=len(crm_ready),
                duplicates=run["summary"]["duplicates"],
                discarded=len(run["discarded"]),
            )
            self._update_autonomous_agent(
                run,
                brief,
                agent_id="crm_packager",
                status="completed",
                summary=(
                    crm_handoff.get("summary")
                    or f"CRM preparado con {len(crm_ready)} leads listos para push y {len(brief.crm_tags)} tags manuales."
                ),
                warnings=self._dedupe_list(
                    [
                        *(crm_handoff.get("warnings") or []),
                        *([] if crm_ready else ["No hay leads listos para CRM con el score y dedupe actuales."]),
                    ]
                ),
                guardrails_applied=[
                    "No empujar duplicados al CRM.",
                    "No preparar handoff sin score minimo ni evidencia.",
                ],
                outputs={
                    "crm_ready_count": len(crm_ready),
                    "manual_tags": brief.crm_tags,
                    "default_tags_preview": default_tags_for_vertical(brief.vertical, geography),
                    "handoff_ready": crm_handoff.get("handoff_ready", bool(crm_ready)),
                    "next_step": crm_handoff.get("next_step", ""),
                },
            )
            run["status"] = "completed"
            self._log(run, f"Run completado | útiles={run['summary']['usable_results']} | descartados={run['summary']['discarded']} | duplicados={run['summary']['duplicates']}", hito=True)
        except Exception as exc:  # pragma: no cover - operational fallback
            run["status"] = "failed"
            run["error"] = str(exc)
            self._update_autonomous_agent(
                run,
                brief,
                agent_id="search_executor",
                status="failed",
                summary="La ejecucion de prospeccion ha fallado antes de completar el pipeline.",
                warnings=[str(exc)],
                guardrails_applied=["Conservar evidencia y error para reintento posterior."],
            )
            self._log(run, f"Error fatal: {exc}", level="error")
        finally:
            run["finished_at"] = datetime.now(timezone.utc).isoformat()
            await self._repository.save_runs(runs)
        return run

    # ── DDG discovery ────────────────────────────────────────────────────────

    async def _discover_with_ddg(
        self,
        run_id: str,
        run: dict[str, Any],
        brief: ProspectingBrief,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        queries = self.generate_queries(brief)
        if self._llm.enabled:
            extra_queries = await self._llm_expand_queries(brief, queries)
            for q in extra_queries:
                if q.lower() not in {item.lower() for item in queries}:
                    queries.append(q)
        self._log(run, f"DDG Search: {len(queries)} queries", queries=queries[:5])
        raw_hits: list[dict[str, Any]] = []
        for query in queries:
            payload = await self._ddg.search(
                run_id=run_id,
                query=query,
                max_results=min(max(brief.desired_count, 5), 20),
            )
            batch = [
                {
                    "query": query,
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "source": "ddg",
                }
                for item in payload.get("results", [])
                if not self._ddg.is_directory_domain(item.get("url", ""))
            ]
            raw_hits.extend(batch)
            self._log(run, f"DDG '{query[:60]}' → {len(batch)} resultados limpios")
        return raw_hits, queries

    # ── Agentic loop helpers ──────────────────────────────────────────────────

    @staticmethod
    def _count_real_domains(raw_hits: list[dict[str, Any]]) -> int:
        """Count unique non-directory domains in the hit list."""
        seen: set[str] = set()
        for hit in raw_hits:
            url = hit.get("url", "")
            if not url:
                continue
            hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if hostname:
                seen.add(hostname)
        return len(seen)

    @staticmethod
    def _merge_raw_hits(
        existing: list[dict[str, Any]],
        new_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Append new_hits to existing, deduplicating by URL."""
        seen: set[str] = {(hit.get("url") or "").rstrip("/").lower() for hit in existing}
        merged = list(existing)
        for hit in new_hits:
            key = (hit.get("url") or "").rstrip("/").lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(hit)
        return merged

    async def _linkedin_pass(
        self,
        results: list[dict[str, Any]],
        brief: ProspectingBrief,
    ) -> None:
        """Attempt to fill contact_person/contact_role from real DDG LinkedIn snippets.

        Only writes to a result if the DDG snippet actually contains the company name,
        so no data is ever invented. Mutates results in-place.
        """
        if not self._ddg.enabled:
            return
        geography = brief.geography_label
        for result in results:
            if result.get("contact_person"):
                continue
            company_name = result.get("name", "")
            if not company_name:
                continue
            contact = await self._ddg.find_linkedin_contact(
                company_name=company_name,
                city=geography,
            )
            if contact:
                result["contact_person"] = contact.get("name", "")
                result["contact_role"] = contact.get("role", "")
                result.setdefault("notes", [])
                if isinstance(result["notes"], list):
                    result["notes"].append(f"Contacto LinkedIn (DDG snippet): {contact.get('source_url','')}")

    async def _discover_with_places(
        self,
        run: dict[str, Any],
        brief: ProspectingBrief,
        *,
        geography: str,
    ) -> tuple[list[dict[str, Any]], list[str]] | None:
        if not self._places.enabled or not geography:
            return [], []
        try:
            self._budget.check_or_raise()
        except BudgetExceededError as exc:
            self._log(run, str(exc), level="error")
            run["status"] = "budget_exceeded"
            run["finished_at"] = datetime.now(timezone.utc).isoformat()
            return None
        budget_before = self._budget.status()
        self._log(
            run,
            f"Buscando en Google Places: {brief.vertical} en {geography}",
            budget_calls=budget_before["calls"],
            budget_remaining=budget_before["remaining"],
        )
        raw_hits, api_calls_made = await self._places.search_by_brief(
            vertical=brief.vertical,
            geography=geography,
            max_results=brief.desired_count * 2,
            language=brief.language,
            target_description=brief.target_description,
        )
        new_total = await self._budget.increment(api_calls_made)
        run["places_api_calls"] = run.get("places_api_calls", 0) + api_calls_made
        self._log(
            run,
            f"Places devolvió {len(raw_hits)} candidatos",
            source="google_places",
            api_calls=api_calls_made,
            budget_total=new_total,
        )
        return raw_hits, [f"[Places] {brief.vertical} en {geography}"]

    async def _discover_with_brave(
        self,
        run_id: str,
        run: dict[str, Any],
        brief: ProspectingBrief,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        queries = self.generate_queries(brief)
        if self._llm.enabled:
            extra_queries = await self._llm_expand_queries(brief, queries)
            for query in extra_queries:
                if query.lower() not in {item.lower() for item in queries}:
                    queries.append(query)
        self._log(run, f"Brave Search: {len(queries)} queries", queries=queries[:5])
        raw_hits: list[dict[str, Any]] = []
        for query in queries:
            payload = await self._brave.search(
                run_id=run_id,
                query=query,
                country=brief.country,
                language=brief.language,
                count=min(max(brief.desired_count, 5), 20),
            )
            batch = [
                {
                    "query": query,
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                }
                for item in payload.get("results", [])
            ]
            raw_hits.extend(batch)
            self._log(run, f"Brave query '{query[:60]}' → {len(batch)} resultados")
        return raw_hits, queries

    async def _llm_expand_queries(self, brief: ProspectingBrief, queries: list[str]) -> list[str]:
        schema_hint = {"queries": ["consulta 1", "consulta 2"]}
        response = await self._llm.extract_json(
            system_prompt=resolve_prompt_sync("sales.prospecting.query_planner"),
            user_prompt=(
                f"Vertical: {brief.vertical}\n"
                f"Objetivo: {brief.target_description}\n"
                f"Geografía: {brief.geography_label}\n"
                f"Must have: {brief.must_have}\n"
                f"Nice to have: {brief.nice_to_have}\n"
                f"Exclude: {brief.exclude}\n"
                f"Queries iniciales: {queries}\n"
                "Propón hasta 4 queries complementarias sin repetir las existentes."
            ),
            schema_hint=schema_hint,
        )
        return [str(item).strip() for item in response.get("queries", []) if str(item).strip()][:4]

    async def _audit_search_phase(
        self,
        brief: ProspectingBrief,
        *,
        queries: list[str],
        used_sources: list[str],
        raw_hits: int,
    ) -> dict[str, Any]:
        if not self._llm.enabled:
            return {}
        response = await self._llm.extract_json(
            system_prompt=resolve_prompt_sync("sales.prospecting.search_audit"),
            user_prompt=(
                f"Brief: {brief.to_dict()}\n"
                f"Queries: {queries}\n"
                f"Sources usadas: {used_sources}\n"
                f"Resultados brutos: {raw_hits}\n"
                "Evalua la calidad del discovery."
            ),
            schema_hint={
                "summary": "Discovery razonable con bajo ruido y cobertura suficiente.",
                "warnings": [],
                "next_adjustment": "",
            },
        )
        return {
            "summary": str(response.get("summary") or "").strip(),
            "warnings": self._parse_list(response.get("warnings")),
            "next_adjustment": str(response.get("next_adjustment") or "").strip(),
        }

    async def _summarize_crm_packager(
        self,
        brief: ProspectingBrief,
        *,
        crm_ready_count: int,
        duplicates: int,
        discarded: int,
    ) -> dict[str, Any]:
        if not self._llm.enabled:
            return {}
        response = await self._llm.extract_json(
            system_prompt=resolve_prompt_sync("sales.prospecting.crm_packager"),
            user_prompt=(
                f"Brief: {brief.to_dict()}\n"
                f"Leads listos para CRM: {crm_ready_count}\n"
                f"Duplicados: {duplicates}\n"
                f"Descartados: {discarded}\n"
                "Resume el handoff comercial."
            ),
            schema_hint={
                "summary": "Handoff listo para CRM con leads no duplicados.",
                "warnings": [],
                "handoff_ready": True,
                "next_step": "Revisar y empujar leads validos al CRM.",
            },
        )
        return {
            "summary": str(response.get("summary") or "").strip(),
            "warnings": self._parse_list(response.get("warnings")),
            "handoff_ready": bool(response.get("handoff_ready", False)),
            "next_step": str(response.get("next_step") or "").strip(),
        }

    async def _extract_candidate(
        self,
        run_id: str,
        run: dict[str, Any],
        candidate: dict[str, Any],
        brief: ProspectingBrief,
    ) -> dict[str, Any]:
        website = self._normalize_url(candidate.get("url", ""))
        extracted = await self._extractor.extract(url=website, vertical=brief.vertical)
        brave_enrichment = await self._enrich_candidate_with_brave(run_id, run, candidate, brief)
        llm_classification = await self._classify_candidate(candidate, extracted, brave_enrichment, brief)
        name = extracted.get("name") or candidate.get("title", "") or llm_classification.get("name", "")
        if not name:
            name = str(candidate.get("url", "")).strip()
        # Teléfono: scraping primero, Places como fallback (ya estructurado)
        phones = extracted.get("phones", [])
        if not phones and candidate.get("phone"):
            phones = [candidate["phone"]]

        # Dirección: Places la da limpia, extractor la infiere del texto
        address = extracted.get("address", "") or candidate.get("address", "")

        return {
            "result_id": f"prosr-{uuid4().hex[:10]}",
            "vertical": brief.vertical,
            "name": name,
            "organization_type": (
                "public_body" if brief.vertical == "public_administration"
                else "restaurant" if brief.vertical == "restaurants"
                else "asesoria" if brief.vertical == "asesoria"
                else "inmobiliaria" if brief.vertical == "inmobiliaria"
                else "custom"
            ),
            "website": extracted.get("website") or website,
            "official_website": bool(llm_classification.get("official_website", brief.vertical == "public_administration" and ".gov" in website or ".es" in website)),
            "domain": extracted.get("domain") or self._extract_domain(website),
            "email": extracted.get("emails", [""])[0] if extracted.get("emails") else "",
            "emails": extracted.get("emails", []),
            "phone": phones[0] if phones else "",
            "phones": phones,
            "address": address,
            "city": extracted.get("city") or brief.city,
            "province": extracted.get("province") or brief.province,
            "contact_person": llm_classification.get("contact_person", ""),
            "contact_role": llm_classification.get("contact_role", ""),
            "source_url": candidate.get("url") or extracted.get("source_url") or website,
            "evidence_urls": self._dedupe_list([*extracted.get("evidence_urls", []), *brave_enrichment.get("evidence_urls", [])]),
            "social_links": extracted.get("social_links", []),
            "quality_signals": self._dedupe_list([*extracted.get("quality_signals", []), *llm_classification.get("quality_signals", [])]),
            "contact_form_only": extracted.get("contact_form_only", False),
            "is_relevant": bool(llm_classification.get("relevant", True)),
            "is_premium": bool(llm_classification.get("is_premium", False)),
            "notes": self._dedupe_list([candidate.get("description", ""), *extracted.get("notes", []), *brave_enrichment.get("notes", []), llm_classification.get("notes", "")]),
            "reason": llm_classification.get("reason", ""),
            # Datos extra de Google Places
            "rating": candidate.get("rating"),
            "rating_count": candidate.get("rating_count", 0),
            "source": candidate.get("source", "google_places"),
            "enrichment_sources": brave_enrichment.get("sources", []),
        }

    async def _enrich_candidate_with_brave(
        self,
        run_id: str,
        run: dict[str, Any],
        candidate: dict[str, Any],
        brief: ProspectingBrief,
    ) -> dict[str, Any]:
        if not self._brave.enabled:
            return {}

        base_name = str(candidate.get("title") or candidate.get("name") or "").strip()
        if not base_name:
            return {}

        geography = str(candidate.get("address") or brief.geography_label or "").strip()
        query_parts = [base_name]
        if geography:
            query_parts.append(geography)
        query_parts.append("contacto")
        query = " ".join(part for part in query_parts if part).strip()
        if not query:
            return {}

        payload = await self._brave.search(
            run_id=run_id,
            query=query,
            country=brief.country,
            language=brief.language,
            count=5,
        )
        results = list(payload.get("results", []))[:3]
        run.setdefault("enrichment_queries", [])
        if query not in run["enrichment_queries"]:
            run["enrichment_queries"].append(query)
        self._log(
            run,
            f"Brave enrich '{base_name[:50]}' -> {len(results)} resultados",
            source="brave_enrichment",
            query=query,
        )
        return {
            "sources": ["brave"],
            "query": query,
            "evidence_urls": [str(item.get("url") or "").strip() for item in results if str(item.get("url") or "").strip()],
            "notes": [str(item.get("description") or "").strip() for item in results if str(item.get("description") or "").strip()],
        }

    async def _classify_candidate(
        self,
        candidate: dict[str, Any],
        extracted: dict[str, Any],
        brave_enrichment: dict[str, Any],
        brief: ProspectingBrief,
    ) -> dict[str, Any]:
        heuristic = self._heuristic_classification(candidate, extracted, brief)
        if not self._llm.enabled:
            return heuristic
        schema_hint = {
            "relevant": True,
            "name": "",
            "city": "",
            "province": "",
            "quality_signals": [],
            "is_premium": False,
            "official_website": False,
            "reason": "",
            "notes": "",
        }
        response = await self._llm.extract_json(
            system_prompt=resolve_prompt_sync("sales.prospecting.classify_candidate"),
            user_prompt=(
                f"Vertical: {brief.vertical}\n"
                f"Objetivo: {brief.target_description}\n"
                f"Geografía: {brief.geography_label}\n"
                f"Candidato base: título={candidate.get('title','')} url={candidate.get('url','')} descripción={candidate.get('description','')}\n"
                f"Señales extraídas: {extracted}\n"
                f"Enriquecimiento Brave: {brave_enrichment}\n"
                "Determina si el negocio encaja y si es apto para prospección."
            ),
            schema_hint=schema_hint,
        )
        merged = dict(heuristic)
        merged["quality_signals"] = self._dedupe_list([*heuristic.get("quality_signals", []), *(response.get("quality_signals") or [])])
        merged["notes"] = self._dedupe_list([heuristic.get("notes", ""), response.get("notes", "")])
        merged["is_premium"] = bool(heuristic.get("is_premium") or response.get("is_premium", False))
        merged["official_website"] = bool(heuristic.get("official_website") or response.get("official_website", False))
        # contact_person and contact_role are NEVER filled by LLM inference — only by
        # real website scraping or LinkedIn DDG snippets. See _linkedin_pass().
        return merged

    def _heuristic_classification(self, candidate: dict[str, Any], extracted: dict[str, Any], brief: ProspectingBrief) -> dict[str, Any]:
        text = " ".join(
            [
                candidate.get("title", ""),
                candidate.get("description", ""),
                extracted.get("name", ""),
                " ".join(extracted.get("quality_signals", [])),
            ]
        ).lower()
        relevant = True
        is_premium = False
        reason = ""
        if brief.vertical == "restaurants":
            premium_signals = ("degustacion", "gourmet", "estrella", "eventos", "reservas", "terraza")
            is_premium = any(token in text for token in premium_signals)
            relevant = "restaurante" in text or "cocina" in text or "reservas" in text
            reason = "restaurante con señales de calidad" if relevant else "no parece restaurante objetivo"
        elif brief.vertical == "asesoria":
            signals = ("asesoría", "asesoria", "gestoría", "gestoria", "fiscal", "laboral", "contabilidad", "irpf", "renta", "impuesto", "autonomos")
            relevant = any(token in text for token in signals)
            reason = "asesoría/gestoría con señales fiscales o laborales" if relevant else "no parece asesoría objetivo"
        elif brief.vertical == "inmobiliaria":
            signals = ("inmobiliaria", "agencia", "pisos", "alquiler", "venta", "propiedades", "casas", "fincas", "chalets")
            relevant = any(token in text for token in signals)
            reason = "inmobiliaria con señales de ventas/alquiler" if relevant else "no parece inmobiliaria"
        elif brief.vertical == "public_administration":
            official_signals = ("ayuntamiento", "sede electrónica", "administración", "concejal", "secretar")
            relevant = any(token in text for token in official_signals) or ".es" in extracted.get("domain", "")
            reason = "organismo público con señales oficiales" if relevant else "no parece organismo oficial"
        elif brief.vertical not in KNOWN_VERTICALS and brief.vertical != "otros":
            relevant = True
            reason = "vertical creada dinámicamente; clasificación heurística genérica"
        else:
            reason = "clasificación heurística genérica"
        return {
            "relevant": relevant,
            "is_premium": is_premium,
            "official_website": brief.vertical == "public_administration" and relevant,
            "quality_signals": extracted.get("quality_signals", []),
            "reason": reason,
            "notes": reason,
        }

    @staticmethod
    def _looks_like_person_name(value: Any) -> bool:
        text = " ".join(str(value or "").strip().split())
        if not text or "@" in text or any(char.isdigit() for char in text):
            return False
        parts = text.split()
        if not (2 <= len(parts) <= 4):
            return False
        blocked = {
            "info",
            "contacto",
            "ventas",
            "admin",
            "administracion",
            "atencion",
            "soporte",
        }
        return all(part.lower().strip(".,") not in blocked for part in parts)

    @staticmethod
    def _looks_like_role_label(value: Any) -> bool:
        text = " ".join(str(value or "").strip().split())
        if not text or "@" in text or any(char.isdigit() for char in text):
            return False
        return len(text) <= 80

    async def _push_single_result(self, result: dict[str, Any], brief: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        crm_blockers = self._crm_blockers(result, self._normalize_brief(brief))
        if crm_blockers:
            return {
                "status": "blocked",
                "message": "El lead requiere revision antes de CRM: " + ", ".join(self._humanize_reason(item) for item in crm_blockers),
                "dry_run": dry_run,
                "result_id": result["result_id"],
            }
        lead_payload = self._build_crm_payload(result, brief)
        if dry_run:
            return {
                "status": "accepted",
                "message": "Preview CRM generada; revisa el payload antes de confirmar.",
                "dry_run": True,
                "result_id": result["result_id"],
                "company_payload": lead_payload["company_payload"],
                "pipeline_payload": lead_payload["pipeline_payload"],
                "note_payload": lead_payload["note_payload"],
                "tags_note_payload": lead_payload["tags_note_payload"],
            }

        existing = await self._find_duplicate(
            result.get("name", ""),
            result.get("domain", ""),
            result.get("email", ""),
            result.get("phone", ""),
        )
        if existing:
            company_id = existing.get("id")
            if company_id:
                await self._connector.add_note(company_id, lead_payload["note_payload"])
                if lead_payload["tags_note_payload"]:
                    await self._connector.add_note(company_id, lead_payload["tags_note_payload"])
            return {
                "status": "accepted",
                "dry_run": False,
                "result_id": result["result_id"],
                "company_id": company_id,
                "reused": True,
            }

        created = await self._connector.create_lead(lead_payload["company_payload"])
        company = created.get("company", {})
        company_id = company.get("id")
        if company_id:
            await self._connector.update_lead(company_id, lead_payload["pipeline_payload"])
            await self._connector.add_note(company_id, lead_payload["note_payload"])
            if lead_payload["tags_note_payload"]:
                await self._connector.add_note(company_id, lead_payload["tags_note_payload"])
        return {
            "status": "accepted",
            "message": "Lead enviado al CRM.",
            "dry_run": False,
            "result_id": result["result_id"],
            "company_id": company_id,
            "company_name": company.get("name") or lead_payload["company_payload"]["name"],
            "reused": False,
        }

    async def _find_duplicate(self, name: str, domain: str, email: str, phone: str) -> dict[str, Any] | None:
        if domain:
            existing = await self._connector.find_company_by_domain(domain)
            if existing:
                return existing
        if email:
            existing = await self._connector.find_company_by_email(email)
            if existing:
                return existing
        if name:
            existing = await self._connector.find_company_by_name(name)
            if existing:
                return existing
        if phone:
            payload = await self._connector.list_pipeline()
            normalized_phone = re.sub(r"\D+", "", phone)
            for company in payload.get("companies", []):
                company_phone = re.sub(r"\D+", "", str(company.get("contact_phone", "")))
                if normalized_phone and company_phone and company_phone == normalized_phone:
                    return company
        return None

    def _build_crm_payload(self, result: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
        followup = datetime.now(timezone.utc).date().isoformat()
        geography = ", ".join(filter(None, [result.get("city"), result.get("province")]))
        vertical = result.get("vertical") or brief.get("vertical", "otros")
        represented_by = brief.get("represented_by", "assets")

        source_note = f"[Google Places]" if result.get("source") == "google_places" else f"[Brave]"
        rating_note = f"Rating Google: {result['rating']}/5 ({result.get('rating_count', 0)} reseñas)" if result.get("rating") else ""

        company_payload = {
            "name": result["name"],
            "domain": result.get("domain", ""),
            "status": "prospect",
            "lead_source": "cold",
            "notes": "\n".join(
                filter(
                    None,
                    [
                        f"Vertical: {vertical}",
                        f"Website: {result.get('website', '')}",
                        f"Dirección: {result.get('address', '')}",
                        f"Geografía: {geography}",
                        f"Fuente: {source_note} {result.get('source_url', '')}",
                        rating_note,
                        f"Score Nexus: {result.get('score', 0)}",
                        f"Razón: {result.get('reason', '')}",
                    ],
                )
            ),
        }
        pipeline_payload = {
            "pipeline_stage": "new",
            "contact_name": result.get("contact_person", ""),
            "contact_email": result.get("email", ""),
            "contact_phone": result.get("phone", ""),
            "lead_source": "cold",
            "next_followup": followup,
            "represented_by": represented_by,
            "sector": vertical if vertical in ("asesoria", "inmobiliaria", "hosteleria", "salud", "legal") else "otros",
            "entry_channel": "import",
            "estimated_value": None,
        }
        note_payload = {
            "note_type": "note",
            "content": (
                f"Prospectado por Nexus ProspectingAgent.\n"
                f"Vertical: {vertical}\n"
                f"Contacto: {result.get('contact_person', '')}\n"
                f"Cargo: {result.get('contact_role', '')}\n"
                f"Email: {result.get('email', '')}\n"
                f"Teléfono: {result.get('phone', '')}\n"
                f"Website: {result.get('website', '')}\n"
                f"Score: {result.get('score', 0)}\n"
                f"Fuente: {result.get('source_url', '')}\n"
                f"Señales: {', '.join(result.get('quality_signals', []))}"
            ).strip(),
            "next_followup": followup,
            "is_done": False,
        }
        tags = list(dict.fromkeys([*default_tags_for_vertical(vertical, geography), *brief.get("crm_tags", [])]))
        tags_note_payload = self._build_tags_note_payload(tags)
        return {
            "company_payload": company_payload,
            "pipeline_payload": pipeline_payload,
            "note_payload": note_payload,
            "tags_note_payload": tags_note_payload,
            "tags": tags,
        }

    def _build_tags_note_payload(self, tags: list[str]) -> dict[str, Any] | None:
        normalized = [str(tag).strip() for tag in tags if str(tag).strip()]
        if not normalized:
            return None
        return {
            "note_type": "note",
            "content": "Tags Nexus aplicadas: " + ", ".join(normalized),
            "is_done": True,
        }

    @staticmethod
    def _clean_location(raw: str) -> str:
        """Strip trailing Spanish filler words from AI-extracted city/province names.
        Example: 'Zaragoza O' (from 'zaragoza o a 20 km') → 'Zaragoza'
        Preserves names like 'A Coruña' (leading article) — only strips trailing tokens.
        """
        _JUNK = {'o', 'a', 'y', 'e', 'u', 'de', 'en', 'km', 'al', 'del', 'su'}
        words = raw.strip().split()
        while len(words) > 1 and words[-1].lower() in _JUNK:
            words.pop()
        return ' '.join(words)

    def _normalize_brief(self, payload: ProspectingRunRequest) -> ProspectingBrief:
        # Si ya viene un vertical decidido (por el LLM contra la lista real del
        # CRM, o escrito a mano en el formulario), se respeta tal cual — no se
        # revalida contra la lista cerrada de KNOWN_VERTICALS, o cualquier
        # vertical real del CRM que no este en esos 7 curados a mano acabaria
        # cayendo a "otros" aqui, pisando lo que ya se habia clasificado bien.
        # normalize_vertical() (con su heuristica de palabras clave y su
        # default a "otros") solo hace falta cuando de verdad no llega nada.
        raw_vertical = (payload.vertical or "").strip()
        vertical = raw_vertical or normalize_vertical("", fallback_text=payload.target_description)
        return ProspectingBrief(
            vertical=vertical,
            target_description=payload.target_description.strip(),
            city=self._clean_location(payload.city),
            province=self._clean_location(payload.province),
            region=payload.region.strip(),
            radius_km=payload.radius_km,
            desired_count=max(1, min(payload.desired_count, 100)),
            must_have=self._parse_list(payload.must_have),
            nice_to_have=self._parse_list(payload.nice_to_have),
            exclude=self._parse_list(payload.exclude),
            crm_tags=self._parse_list(payload.crm_tags),
            campaign_type=payload.campaign_type.strip(),
            minimum_score=max(0, min(payload.minimum_score, 100)),
            country=payload.country.strip() or "es",
            language=payload.language.strip() or "es",
            dry_run=payload.dry_run,
            async_mode=payload.async_mode,
            represented_by=payload.represented_by.strip() or "assets",
            vertical_created=False,
            min_employees=payload.min_employees,
            max_employees=payload.max_employees,
            industrial_zone=payload.industrial_zone.strip(),
            max_run_minutes=max(2, min(payload.max_run_minutes, 30)),
        )

    def _parse_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            items = value
        else:
            items = str(value or "").split(",")
        return [str(item).strip() for item in items if str(item).strip()]

    def _update_autonomous_agent(
        self,
        run: dict[str, Any],
        brief: ProspectingBrief,
        *,
        agent_id: str,
        status: str,
        summary: str,
        warnings: list[str] | None = None,
        guardrails_applied: list[str] | None = None,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        orchestration = run.setdefault("orchestration", {})
        current = orchestration.get("autonomous_agents")
        updated = self._autonomy.update_agent(
            current,
            brief=brief,
            agent_id=agent_id,
            status=status,
            summary=summary,
            warnings=warnings,
            guardrails_applied=guardrails_applied,
            inputs=inputs,
            outputs=outputs,
        )
        orchestration["autonomous_agents"] = self._autonomy.snapshot(updated)

    def _new_run(self, run_id: str, brief: ProspectingBrief, *, source_plan: dict[str, Any] | None = None) -> dict[str, Any]:
        orchestration = self._autonomy.bootstrap(brief)
        orchestration = self._autonomy.update_agent(
            orchestration,
            brief=brief,
            agent_id="brief_guardian",
            status="completed",
            summary="Brief normalizado y protegido antes de entrar en ejecucion.",
            guardrails_applied=[
                "No tocar geografia declarada.",
                "No tocar marca representada.",
                "No inventar volumen objetivo.",
            ],
            outputs={"brief_snapshot": brief.to_dict()},
        )
        orchestration = self._autonomy.update_agent(
            orchestration,
            brief=brief,
            agent_id="brief_refiner",
            status="completed",
            summary="El run parte de un brief estructurado listo para prospeccion.",
            guardrails_applied=["Must/Nice/Exclude pueden evolucionar sin alterar la intencion base."],
            outputs={
                "target_description": brief.target_description,
                "must_have": brief.must_have,
                "nice_to_have": brief.nice_to_have,
                "exclude": brief.exclude,
                "crm_tags": brief.crm_tags,
            },
        )
        orchestration = self._autonomy.update_agent(
            orchestration,
            brief=brief,
            agent_id="source_strategist",
            status="completed",
            summary=(source_plan or self._orchestrator.plan_sources(brief)).get("summary", ""),
            guardrails_applied=["Solo se usan fuentes habilitadas y coherentes con el brief."],
            outputs={"source_plan": source_plan or self._orchestrator.plan_sources(brief)},
        )
        return {
            "run_id": run_id,
            "status": "pending",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "brief": brief.to_dict(),
            "queries": [],
            "results": [],
            "discarded": [],
            "summary": self._empty_summary(),
            "error": None,
            "discovery_source": "google_places" if self._places.enabled else "none",
            "orchestration": {
                "source_plan": source_plan or self._orchestrator.plan_sources(brief),
                "autonomous_agents": self._autonomy.snapshot(orchestration),
            },
            "runtime": {
                "llm": self._llm.descriptor,
                "brave_enabled": self._brave.enabled,
                "places_enabled": self._places.enabled,
                "crm_configured": self._connector.configured,
            },
        }

    def _run_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": run.get("status", "pending"),
            "run_id": run.get("run_id"),
            "summary": run.get("summary", {}),
            "results_count": len(run.get("results", [])),
            "discarded_count": len(run.get("discarded", [])),
            "dry_run": bool((run.get("brief") or {}).get("dry_run", True)),
            "queries": run.get("queries", []),
            "orchestration": run.get("orchestration"),
        }

    def _empty_summary(self) -> dict[str, int]:
        return {
            "raw_candidates": 0,
            "usable_results": 0,
            "crm_ready": 0,
            "duplicates": 0,
            "discarded": 0,
            "pushed_to_crm": 0,
            "errors": 0,
        }

    def _dedupe_candidates(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            url = self._normalize_url(item.get("url", ""))
            title = str(item.get("title") or "").strip().lower()
            key = f"{url}|{title}"
            if not url or key in seen:
                continue
            seen.add(key)
            result.append({**item, "url": url})
        return result

    def _normalize_url(self, value: str | None) -> str:
        if not value:
            return ""
        value = value.strip()
        if not value:
            return ""
        if value.startswith("//"):
            value = f"https:{value}"
        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"
        return value.rstrip("/")

    def _extract_domain(self, website: str) -> str:
        if not website:
            return ""
        return (urlparse(website).hostname or "").lower()

    def _dedupe_list(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return result

    _DEAD_PAGE_PATTERNS = (
        "pagina no encontrada",
        "página no encontrada",
        "page not found",
        "404 not found",
        "error 404",
        "no existe la pagina",
        "no existe la página",
        "contenido no encontrado",
        "this page could not be found",
    )

    def _is_dead_page(self, candidate: dict[str, Any], extracted: dict[str, Any]) -> bool:
        """Return True if the page title or extracted name indicates a 404 / missing page."""
        title_blob = _normalize_text(" ".join([
            str(candidate.get("title", "")),
            str(extracted.get("name", "")),
        ]))
        return any(pat in title_blob for pat in self._DEAD_PAGE_PATTERNS)

    def _evaluate_candidate_guardrails(
        self,
        candidate: dict[str, Any],
        extracted: dict[str, Any],
        brief: ProspectingBrief,
    ) -> list[str]:
        failures: list[str] = []
        if self._is_dead_page(candidate, extracted):
            failures.append("page_not_found")
            return self._dedupe_list(failures)
        if self._looks_like_blocked_listing(candidate, extracted, brief.vertical):
            failures.append("marketplace_or_directory")
        if not bool(extracted.get("is_relevant", True)):
            failures.append("vertical_mismatch")
        if not self._matches_requested_geography(candidate, extracted, brief):
            failures.append("geography_mismatch")
        if self._requires_direct_contact(brief) and not (extracted.get("email") or extracted.get("phone")):
            failures.append("missing_direct_contact")
        failures.extend(self._evaluate_must_have(extracted, brief))
        return self._dedupe_list(failures)

    def _evaluate_must_have(self, extracted: dict[str, Any], brief: ProspectingBrief) -> list[str]:
        failures: list[str] = []
        website = bool(extracted.get("website"))
        phone = bool(extracted.get("phone"))
        email = bool(extracted.get("email"))
        address = bool(extracted.get("address"))
        social_links = extracted.get("social_links", [])
        own_website = website and not self._looks_like_blocked_listing({}, extracted, brief.vertical)

        for raw_item in brief.must_have:
            item = _normalize_text(raw_item)
            if "email" in item and not email:
                failures.append("must_have_email")
            elif "telefono" in item and not phone:
                failures.append("must_have_phone")
            elif "web propia" in item and not own_website:
                failures.append("must_have_own_website")
            elif "web oficial" in item and not own_website:
                failures.append("must_have_own_website")
            elif "portal propio" in item and not own_website:
                failures.append("must_have_own_website")
            elif "direccion" in item and not address:
                failures.append("must_have_address")
            elif "linkedin" in item and not any("linkedin.com" in str(link).lower() for link in social_links):
                failures.append("must_have_linkedin")
        return failures

    def _requires_direct_contact(self, brief: ProspectingBrief) -> bool:
        if brief.vertical in {"asesoria", "inmobiliaria", "restaurants", "salud"}:
            return True
        requested = " ".join([brief.target_description, *brief.must_have]).lower()
        return any(token in requested for token in ("email", "telefono", "teléfono", "contacto"))

    def _looks_like_blocked_listing(
        self,
        candidate: dict[str, Any],
        extracted: dict[str, Any],
        vertical: str,
    ) -> bool:
        blob = _normalize_text(
            " ".join(
                [
                    str(candidate.get("title", "")),
                    str(candidate.get("description", "")),
                    str(candidate.get("url", "")),
                    str(extracted.get("website", "")),
                    str(extracted.get("domain", "")),
                    str(extracted.get("name", "")),
                ]
            )
        )
        for hint in [*BLOCKED_HINT_PREFIXES, *VERTICAL_BLOCKLIST.get(vertical, ())]:
            if _normalize_text(hint) in blob:
                return True
        if vertical == "inmobiliaria":
            return any(token in blob for token in ("portal inmobiliario", "anuncios de pisos", "buscador de viviendas"))
        return False

    def _matches_requested_geography(
        self,
        candidate: dict[str, Any],
        extracted: dict[str, Any],
        brief: ProspectingBrief,
    ) -> bool:
        requested_city = _normalize_text(brief.city)
        requested_province = _normalize_text(brief.province)
        if not requested_city and not requested_province:
            return True
        blob = _normalize_text(
            " ".join(
                [
                    str(candidate.get("title", "")),
                    str(candidate.get("description", "")),
                    str(extracted.get("address", "")),
                    str(extracted.get("city", "")),
                    str(extracted.get("province", "")),
                    str(extracted.get("name", "")),
                    " ".join(str(item) for item in extracted.get("notes", [])),
                ]
            )
        )
        city_ok = not requested_city or requested_city in blob
        province_ok = not requested_province or requested_province in blob or city_ok
        return city_ok and province_ok

    def _crm_blockers(self, result: dict[str, Any], brief: ProspectingBrief) -> list[str]:
        blockers: list[str] = []
        if result.get("crm_duplicate"):
            blockers.append("crm_duplicate")
        if int(result.get("score", 0)) < int(brief.minimum_score):
            blockers.append("score_below_threshold")
        if self._requires_direct_contact(brief) and not (result.get("email") or result.get("phone")):
            blockers.append("missing_direct_contact")
        return self._dedupe_list(blockers)

    def _humanize_reason(self, reason: str | None) -> str:
        mapping = {
            "page_not_found": "pagina no encontrada (404)",
            "marketplace_or_directory": "portal o directorio",
            "vertical_mismatch": "no encaja con la vertical pedida",
            "geography_mismatch": "fuera de la geografia pedida",
            "missing_direct_contact": "sin telefono ni email util",
            "must_have_email": "falta email directo",
            "must_have_phone": "falta telefono",
            "must_have_own_website": "no tiene web propia",
            "must_have_address": "falta direccion visible",
            "must_have_linkedin": "falta LinkedIn",
            "crm_duplicate": "ya existe en CRM",
            "score_below_threshold": "score por debajo del minimo",
            "no_website": "sin web",
        }
        return mapping.get(str(reason or ""), str(reason or "motivo no disponible"))

    def _locate_result(self, runs: list[dict[str, Any]], result_id: str) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
        for run_index, run in enumerate(runs):
            for result in run.get("results", []):
                if result.get("result_id") == result_id:
                    return run_index, run, result
        return None


MunicipalProspectorService = ProspectingAgentService


