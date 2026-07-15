"""SearchGuardrailAgent — verifica si un resultado cumple los criterios del search intent.

Standalone. No modifica nada del pipeline existente.
Cada criterio es un check independiente con evidencia observable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from agents.llm_router import get_router
from nexus.prompts import resolve_prompt_sync


# ── Verificadores locales (sin LLM) ──────────────────────────────────────────

_CORPORATE_DOMAIN_PATTERNS = [
    r"^[a-z0-9\-]+\.[a-z0-9\-]+\.(vitaldent|sanitasdental|clinicabaviera|dentix|orthodontic|impress)\.com",
    r"\.(es|com)/(es|cl)(-[a-z]+)?/[a-z]+-[a-z]+",
]

_EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def _check_has_email_local(candidate: dict[str, Any]) -> dict[str, Any]:
    email = candidate.get("email", "")
    emails = candidate.get("emails", [])
    contact_form_only = candidate.get("contact_form_only", False)

    if email and _EMAIL_REGEX.match(email):
        return {
            "criterion": "has_email",
            "result": "pass",
            "evidence": f"Email encontrado: {email}",
            "reasoning": "Hay un email directo extraído de la web",
            "needs_navigation": False,
        }
    if emails:
        return {
            "criterion": "has_email",
            "result": "pass",
            "evidence": f"Emails encontrados: {', '.join(emails[:3])}",
            "reasoning": "Hay emails directos extraídos de la web",
            "needs_navigation": False,
        }
    if contact_form_only:
        return {
            "criterion": "has_email",
            "result": "fail",
            "evidence": "Solo tiene formulario de contacto, sin email directo",
            "reasoning": "Un formulario no es un email directo",
            "needs_navigation": False,
        }
    website = candidate.get("website") or candidate.get("source_url", "")
    if website:
        return {
            "criterion": "has_email",
            "result": "uncertain",
            "evidence": f"Web disponible ({website}) pero no se encontró email en la extracción",
            "reasoning": "Podría estar en una subpágina de contacto no visitada",
            "needs_navigation": True,
        }
    return {
        "criterion": "has_email",
        "result": "fail",
        "evidence": "Sin web y sin email",
        "reasoning": "No hay forma de obtener contacto directo",
        "needs_navigation": False,
    }


def _check_has_phone_local(candidate: dict[str, Any]) -> dict[str, Any]:
    phone = candidate.get("phone", "")
    phones = candidate.get("phones", [])
    if phone or phones:
        found = phone or phones[0]
        return {
            "criterion": "has_phone",
            "result": "pass",
            "evidence": f"Teléfono encontrado: {found}",
            "reasoning": "Hay un teléfono de contacto directo",
            "needs_navigation": False,
        }
    return {
        "criterion": "has_phone",
        "result": "fail",
        "evidence": "No se encontró ningún teléfono",
        "reasoning": "Sin teléfono visible en la extracción",
        "needs_navigation": bool(candidate.get("website")),
    }


def _check_has_own_website_local(candidate: dict[str, Any]) -> dict[str, Any]:
    website = candidate.get("website", "")
    domain = candidate.get("domain", "")

    _GENERIC_DIRS = (
        "facebook.com", "instagram.com", "linkedin.com", "paginasamarillas",
        "yelp.", "tripadvisor.", "google.com", "maps.google",
    )
    blob = f"{website} {domain}".lower()
    for hint in _GENERIC_DIRS:
        if hint in blob:
            return {
                "criterion": "has_own_website",
                "result": "fail",
                "evidence": f"La URL pertenece a un directorio o red social: {website}",
                "reasoning": f"Dominio genérico detectado: {hint}",
                "needs_navigation": False,
            }
    if website:
        return {
            "criterion": "has_own_website",
            "result": "pass",
            "evidence": f"Web propia encontrada: {website}",
            "reasoning": "Dominio no es directorio conocido",
            "needs_navigation": False,
        }
    return {
        "criterion": "has_own_website",
        "result": "fail",
        "evidence": "No se encontró URL de web propia",
        "reasoning": "Sin web no se puede verificar",
        "needs_navigation": False,
    }


def _check_not_chain_local(
    candidate: dict[str, Any],
    known_examples: list[str],
) -> dict[str, Any] | None:
    """Devuelve resultado si puede determinarse sin LLM, None si necesita LLM."""
    name = (candidate.get("name") or candidate.get("title") or "").strip()
    domain = (candidate.get("domain") or "").lower()
    website = (candidate.get("website") or "").lower()

    # 1. Check por nombre contra lista conocida
    name_lower = name.lower()
    for chain in known_examples:
        if chain.lower() in name_lower:
            return {
                "criterion": "not_chain",
                "result": "fail",
                "evidence": f"El nombre '{name}' contiene '{chain}', una cadena conocida",
                "reasoning": "Nombre coincide con cadena de la lista conocida",
                "needs_navigation": False,
            }

    # 2. Check de dominio corporativo (subdominio + sufijo conocido)
    for pattern in _CORPORATE_DOMAIN_PATTERNS:
        if re.search(pattern, domain):
            return {
                "criterion": "not_chain",
                "result": "fail",
                "evidence": f"El dominio '{domain}' tiene estructura de cadena corporativa",
                "reasoning": "Patrón de subdominio corporativo detectado",
                "needs_navigation": False,
            }

    # 3. Si el nombre tiene estructura de cadena pero no está en la lista → LLM
    chain_signals = ("grupo", "group", "clínicas", "clinicas", "dental centers",
                     "dental centre", "salud dental", "red de", "cadena de")
    blob = name_lower + " " + domain
    for signal in chain_signals:
        if signal in blob:
            return None  # señal dudosa → escala a LLM

    # Sin señales de cadena → pass local
    return {
        "criterion": "not_chain",
        "result": "pass",
        "evidence": f"Nombre '{name}' y dominio '{domain}' no muestran señales de cadena",
        "reasoning": "Sin coincidencias con cadenas conocidas ni patrones corporativos",
        "needs_navigation": False,
    }


def _check_not_directory_local(candidate: dict[str, Any]) -> dict[str, Any]:
    website = (candidate.get("website") or "").lower()
    domain = (candidate.get("domain") or "").lower()
    _DIRS = (
        "paginasamarillas", "yelp.", "tripadvisor.", "thefork.",
        "emagister.", "infocif.", "einforma.", "axesor.", "empresite.",
        "kompass.", "europages.", "tododiscos.",
    )
    blob = website + " " + domain
    for hint in _DIRS:
        if hint in blob:
            return {
                "criterion": "not_directory",
                "result": "fail",
                "evidence": f"El dominio '{domain}' es un directorio conocido",
                "reasoning": f"Directorio detectado: {hint}",
                "needs_navigation": False,
            }
    return {
        "criterion": "not_directory",
        "result": "pass",
        "evidence": f"Dominio '{domain}' no es directorio conocido",
        "reasoning": "Sin coincidencias con directorios bloqueados",
        "needs_navigation": False,
    }


# ── Agente principal ──────────────────────────────────────────────────────────

class SearchGuardrailAgent:
    """Verifica si un resultado cumple los criterios del search intent.

    Uso:
        agent = SearchGuardrailAgent()
        checks = await agent.verify(candidate, search_intent)
        # checks = [{"criterion": "has_email", "result": "pass", ...}, ...]
    """

    async def verify(
        self,
        candidate: dict[str, Any],
        search_intent: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Ejecuta todos los guardrail checks para un candidato."""
        criteria = search_intent.get("guardrail_criteria", [])
        inclusions = {i["criterion"]: i for i in search_intent.get("inclusions", [])}
        exclusions = {e["criterion"]: e for e in search_intent.get("exclusions", [])}

        results = []
        for criterion in criteria:
            check = await self._check_criterion(criterion, candidate, inclusions, exclusions, search_intent)
            results.append(check)
            logger.debug(
                "guardrail | {} → {} | {}",
                criterion,
                check["result"],
                check["evidence"][:80],
            )
        return results

    def aggregate(self, checks: list[dict[str, Any]]) -> dict[str, Any]:
        """Resume el resultado de todos los checks en una decisión final."""
        if not checks:
            return {"decision": "pass", "failed": [], "uncertain": [], "passed": []}

        failed = [c for c in checks if c["result"] == "fail"]
        uncertain = [c for c in checks if c["result"] == "uncertain"]
        passed = [c for c in checks if c["result"] == "pass"]

        if failed:
            decision = "fail"
            reason = f"Falló: {', '.join(c['criterion'] for c in failed)}"
        elif uncertain:
            decision = "uncertain"
            reason = f"Incierto: {', '.join(c['criterion'] for c in uncertain)}"
        else:
            decision = "pass"
            reason = "Todos los criterios cumplidos"

        return {
            "decision": decision,
            "reason": reason,
            "failed": [c["criterion"] for c in failed],
            "uncertain": [c["criterion"] for c in uncertain],
            "passed": [c["criterion"] for c in passed],
            "checks": checks,
        }

    async def _check_criterion(
        self,
        criterion: str,
        candidate: dict[str, Any],
        inclusions: dict[str, Any],
        exclusions: dict[str, Any],
        search_intent: dict[str, Any],
    ) -> dict[str, Any]:
        if criterion == "has_email":
            return _check_has_email_local(candidate)

        if criterion == "has_phone":
            return _check_has_phone_local(candidate)

        if criterion == "has_own_website":
            return _check_has_own_website_local(candidate)

        if criterion == "not_directory":
            return _check_not_directory_local(candidate)

        if criterion == "not_chain":
            excl_def = exclusions.get("not_chain", {})
            known_examples = excl_def.get("known_examples", [])
            local_result = _check_not_chain_local(candidate, known_examples)
            if local_result is not None:
                return local_result
            # Escala a LLM solo cuando hay señal dudosa
            return await self._llm_check(criterion, candidate, search_intent)

        # Criterio desconocido → LLM decide
        return await self._llm_check(criterion, candidate, search_intent)

    async def _llm_check(
        self,
        criterion: str,
        candidate: dict[str, Any],
        search_intent: dict[str, Any],
    ) -> dict[str, Any]:
        """Último recurso: el LLM evalúa el criterio con los datos disponibles."""
        try:
            import asyncio
            llm = get_router()
            context = {
                "criterion": criterion,
                "candidate": {
                    "name": candidate.get("name") or candidate.get("title"),
                    "domain": candidate.get("domain"),
                    "website": candidate.get("website"),
                    "email": candidate.get("email"),
                    "address": candidate.get("address"),
                    "quality_signals": candidate.get("quality_signals", []),
                    "notes": candidate.get("notes", [])[:3],
                },
                "search_intent": {
                    "business_type": search_intent.get("business_type"),
                    "exclusions": search_intent.get("exclusions", []),
                },
            }
            response = await asyncio.wait_for(
                llm.call(
                    messages=[
                        {"role": "system", "content": resolve_prompt_sync("sales.prospecting.guardrail_check")},
                        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                    ],
                    preferred_level=1,
                    temperature=0.0,
                    max_tokens=300,
                    timeout=6.0,
                ),
                timeout=10.0,
            )
        except Exception as exc:
            logger.warning("guardrail | LLM check falló para '{}': {}", criterion, exc)
            return {
                "criterion": criterion,
                "result": "uncertain",
                "evidence": f"LLM no disponible: {exc}",
                "reasoning": "No se pudo verificar sin LLM",
                "needs_navigation": False,
            }

        if response is None or response.error:
            return {
                "criterion": criterion,
                "result": "uncertain",
                "evidence": "LLM devolvió error",
                "reasoning": "No se pudo verificar",
                "needs_navigation": False,
            }

        raw = (response.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            return {
                "criterion": criterion,
                "result": "uncertain",
                "evidence": "LLM devolvió respuesta no parseable",
                "reasoning": raw[:100],
                "needs_navigation": False,
            }
        try:
            parsed = json.loads(raw[start : end + 1])
            parsed.setdefault("criterion", criterion)
            parsed.setdefault("needs_navigation", False)
            return parsed
        except Exception:
            return {
                "criterion": criterion,
                "result": "uncertain",
                "evidence": "JSON inválido del LLM",
                "reasoning": raw[:100],
                "needs_navigation": False,
            }
