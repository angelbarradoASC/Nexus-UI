"""Heuristic technical web audit built on top of Obscura (real headless browser).

No es Lighthouse — no hay Core Web Vitals ni axe-core. Es una aproximacion
pragmatica pensada para sostener una observacion concreta y defendible en el
mensaje de contacto ("vuestra web tarda X, no tiene version movil..."), no un
informe SEO exhaustivo. Reutiliza el mismo binario que ya usa
WebProspectExtractor para renderizar paginas — cero dependencias nuevas.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.prospecting.extractors import _default_obscura_binary

# Un solo eval recoge todo lo que se puede medir desde dentro de la pagina ya
# renderizada: tiempos de red/pintado (Navigation + Paint Timing API), señales
# de mobile-friendliness, presencia de formulario/CTA/WhatsApp/telefono, e
# imagenes sin alt. Mismo patron que _PAGE_EVAL_SCRIPT en extractors.py.
_AUDIT_EVAL_SCRIPT = (
    "JSON.stringify({"
    "load_time_ms: (function(){"
    "try {"
    "var nav = performance.getEntriesByType('navigation')[0];"
    "if (nav) return Math.round(nav.loadEventEnd || nav.duration || 0);"
    "var t = performance.timing;"
    "return t.loadEventEnd && t.navigationStart ? (t.loadEventEnd - t.navigationStart) : null;"
    "} catch(e) { return null; }"
    "})(),"
    "ttfb_ms: (function(){"
    "try {"
    "var nav = performance.getEntriesByType('navigation')[0];"
    "return nav ? Math.round(nav.responseStart) : null;"
    "} catch(e) { return null; }"
    "})(),"
    "has_viewport_meta: !!document.querySelector('meta[name=\"viewport\"]'),"
    "is_https: location.protocol === 'https:',"
    "images_total: document.querySelectorAll('img').length,"
    "images_without_alt: Array.from(document.querySelectorAll('img'))"
    ".filter(function(img){ return !img.getAttribute('alt') || !img.getAttribute('alt').trim(); }).length,"
    "has_contact_form: !!document.querySelector('form'),"
    "has_whatsapp: /wa\\.me|api\\.whatsapp\\.com|whatsapp:\\/\\//i.test(document.documentElement.outerHTML),"
    "has_phone_link: !!document.querySelector('a[href^=\"tel:\"]'),"
    "has_cta: Array.from(document.querySelectorAll('a,button')).some(function(el){"
    "var t = (el.innerText || '').toLowerCase();"
    "return /contact|contacto|reserva|presupuesto|llama|whatsapp|comprar|solicit/.test(t);"
    "}),"
    "title_length: (document.title || '').length"
    "})"
)


@dataclass(slots=True)
class WebAuditor:
    timeout_seconds: float = 15.0
    obscura_binary_path: str = ""

    async def audit(self, website: str) -> dict[str, Any] | None:
        """Devuelve un technical_audit dict, o None si Obscura no esta disponible
        o la auditoria falla (nunca lanza — un fallo aqui no debe tumbar el
        candidato que la pidio, igual que el resto de pasos por candidato de
        _execute_run)."""
        if not website:
            return None
        binary = self._resolve_obscura_binary()
        if binary is None:
            return None
        raw = await self._run_obscura_eval(binary, website)
        if raw is None:
            return None
        return self._build_findings(raw)

    def _resolve_obscura_binary(self) -> Path | None:
        candidate = Path(self.obscura_binary_path) if self.obscura_binary_path else _default_obscura_binary()
        return candidate if candidate.is_file() else None

    async def _run_obscura_eval(self, binary: Path, website: str) -> dict[str, Any] | None:
        args = [
            str(binary), "scrape", website,
            "--stealth",
            "--format", "json",
            "--quiet",
            "--timeout", str(max(int(self.timeout_seconds), 5)),
            "-e", _AUDIT_EVAL_SCRIPT,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds + 15)
            payload = json.loads(stdout.decode("utf-8", errors="ignore") or "{}")
        except Exception:
            return None

        results = payload.get("results") or []
        if not results:
            return None
        raw_eval = results[0].get("eval")
        if not raw_eval:
            return None
        try:
            parsed = json.loads(raw_eval)
        except (TypeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_findings(self, raw: dict[str, Any]) -> dict[str, Any]:
        findings: list[str] = []

        load_time_ms = raw.get("load_time_ms")
        if isinstance(load_time_ms, (int, float)) and load_time_ms > 4000:
            findings.append(f"La web tarda {round(load_time_ms / 1000, 1)}s en cargar por completo")

        mobile_friendly = bool(raw.get("has_viewport_meta"))
        if not mobile_friendly:
            findings.append("No tiene configuracion de viewport para movil (meta viewport ausente)")

        if not raw.get("is_https"):
            findings.append("La web no usa HTTPS")

        images_total = int(raw.get("images_total") or 0)
        images_without_alt = int(raw.get("images_without_alt") or 0)
        if images_total > 0 and images_without_alt == images_total:
            findings.append("Ninguna imagen tiene texto alternativo (alt)")

        if not raw.get("has_contact_form") and not raw.get("has_phone_link"):
            findings.append("No hay formulario de contacto ni telefono en la pagina analizada")

        if not raw.get("has_whatsapp"):
            findings.append("No hay enlace directo a WhatsApp")

        if not raw.get("has_cta"):
            findings.append("No se detecta ninguna llamada a la accion clara (contacto, reserva, presupuesto...)")

        return {
            "load_time_ms": load_time_ms,
            "ttfb_ms": raw.get("ttfb_ms"),
            "mobile_friendly": mobile_friendly,
            "https": bool(raw.get("is_https")),
            "images_total": images_total,
            "images_without_alt": images_without_alt,
            "has_contact_form": bool(raw.get("has_contact_form")),
            "has_whatsapp": bool(raw.get("has_whatsapp")),
            "has_phone_link": bool(raw.get("has_phone_link")),
            "has_cta": bool(raw.get("has_cta")),
            "findings": findings,
            "audited_at": datetime.now(timezone.utc).isoformat(),
        }
