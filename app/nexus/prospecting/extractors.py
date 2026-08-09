"""Website extraction helpers for prospecting candidates."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

_PHONE_RE = re.compile(r"(?:\+34\s*)?(?:\d[\s().-]?){9,14}")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_ADDRESS_RE = re.compile(r"(?:calle|plaza|avenida|avda|paseo|c\\/|c\\.)\s+[^\n,]{4,}", re.IGNORECASE)
_SOCIAL_HINTS = ("instagram.com", "facebook.com", "linkedin.com", "tripadvisor.", "thefork.", "google.")
# link_hints y quality_signal_tokens por defecto (usados si la vertical no trae
# su propia configuracion de discovery) — antes eran los hints de "restaurants",
# ahora son solo el fallback generico.
_DEFAULT_LINK_HINTS = ("contacto", "contact", "reservas", "reservation", "menu", "carta", "eventos", "about", "legal")

# Un solo render por pagina saca texto real (post-JS), titulo y todos los
# enlaces (ya resueltos a absolutos por el DOM) — evita una segunda pasada
# solo para descubrir links, y funciona igual de bien en sitios estaticos que
# en SPAs, a diferencia del scraping por HTML crudo de antes.
#
# El texto se arma nodo-de-texto a nodo-de-texto con TreeWalker (no
# document.body.innerText): innerText no separa elementos inline adyacentes
# sin salto de linea (ej. "email@dominio.es" pegado a "Tel:" sale como
# "email@dominio.estel"), y eso rompe los regex de email/telefono. Con
# TreeWalker cada nodo de texto se une con un separador explicito, igual que
# hacia BeautifulSoup con get_text(" ", ...) en el extractor anterior.
_PAGE_EVAL_SCRIPT = (
    "JSON.stringify({"
    "text: (function(){"
    "if (!document.body) return '';"
    "var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);"
    "var parts = [];"
    "while (w.nextNode()) {"
    "var t = w.currentNode.textContent.trim();"
    "if (t) parts.push(t);"
    "}"
    "return parts.join(' \\n ');"
    "})(),"
    "title: document.title || '',"
    "links: Array.from(document.querySelectorAll('a[href]')).map("
    "a => ({href: a.href, text: (a.innerText || '').trim()})"
    ")"
    "})"
)


def _default_obscura_binary() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    name = "obscura.exe" if sys.platform == "win32" else "obscura"
    return repo_root / "vendor" / "obscura" / name


@dataclass(slots=True)
class WebProspectExtractor:
    timeout_seconds: float = 12.0
    user_agent: str = "Open-Nexus Prospecting/1.0"
    max_pages_per_site: int = 4
    obscura_binary_path: str = ""  # vacio = autodetectar vendor/obscura/obscura[.exe]

    async def extract(
        self,
        *,
        url: str,
        link_hints: list[str] | None = None,
        quality_signal_tokens: list[str] | None = None,
    ) -> dict[str, Any]:
        link_hints = list(link_hints) if link_hints else list(_DEFAULT_LINK_HINTS)
        quality_signal_tokens = list(quality_signal_tokens) if quality_signal_tokens else []
        website = self._normalize_url(url)
        if not website:
            return {"source_url": "", "evidence_urls": [], "emails": [], "phones": [], "social_links": []}

        binary = self._resolve_obscura_binary()
        if binary is not None:
            result = await self._extract_via_obscura(binary, website, link_hints, quality_signal_tokens)
            if result is not None:
                return result
            # Obscura fallo (timeout, red bloqueada...) — degradar a httpx estatico

        return await self._extract_via_httpx(website, link_hints, quality_signal_tokens)

    # ── Obscura: navegador headless real, modo stealth (usuario anonimo) ──────

    async def _extract_via_obscura(
        self,
        binary: Path,
        website: str,
        link_hints: list[str],
        quality_signal_tokens: list[str],
    ) -> dict[str, Any] | None:
        base_pages = await self._obscura_scrape(binary, [website])
        if not base_pages:
            return None
        base_page = base_pages[0]

        extra_links = self._select_candidate_links(base_page.get("links") or [], link_hints)
        extra_links = extra_links[: max(self.max_pages_per_site - 1, 0)]
        extra_pages = await self._obscura_scrape(binary, extra_links) if extra_links else []

        return self._build_result_from_pages(website, [base_page, *extra_pages], quality_signal_tokens)

    async def _obscura_scrape(self, binary: Path, urls: list[str]) -> list[dict[str, Any]]:
        """Navega una o varias URLs con Obscura en modo stealth (fingerprint de
        navegador normal, sin marca de bot) y devuelve, por cada una, el texto
        renderizado, el titulo y los enlaces — todo en un unico render por pagina.
        """
        if not urls:
            return []
        args = [
            str(binary), "scrape", *urls,
            "--stealth",
            "--format", "json",
            "--quiet",
            "--timeout", str(max(int(self.timeout_seconds), 5)),
            "-e", _PAGE_EVAL_SCRIPT,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds * max(len(urls), 1) + 20
            )
            payload = json.loads(stdout.decode("utf-8", errors="ignore") or "{}")
        except Exception:
            return []

        pages: list[dict[str, Any]] = []
        for item in payload.get("results", []):
            raw_eval = item.get("eval")
            if not raw_eval:
                continue
            try:
                parsed = json.loads(raw_eval)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(parsed, dict):
                continue
            parsed["_page_url"] = str(item.get("url") or "")
            pages.append(parsed)
        return pages

    def _select_candidate_links(self, links: list[dict[str, Any]], hints: list[str]) -> list[str]:
        selected: list[str] = []
        for link in links:
            href = str(link.get("href") or "").strip()
            label = str(link.get("text") or "").strip().lower()
            if not href.startswith(("http://", "https://")):
                continue
            low_href = href.lower()
            if any(hint in low_href or hint in label for hint in hints):
                selected.append(href)
        return self._dedupe(selected)

    def _build_result_from_pages(
        self, website: str, pages: list[dict[str, Any]], quality_signal_tokens: list[str]
    ) -> dict[str, Any]:
        domain = (urlparse(website).hostname or "").lower()
        title = str(pages[0].get("title") or "") if pages else ""
        all_text: list[str] = []
        emails: list[str] = []
        phones: list[str] = []
        addresses: list[str] = []
        social_links: list[str] = []
        evidence_urls: list[str] = []
        notes: list[str] = []

        for page in pages:
            page_url = str(page.get("_page_url") or website)
            text = str(page.get("text") or "")
            all_text.append(text)

            found_emails = [item.lower() for item in _EMAIL_RE.findall(text)]
            found_phones = [self._clean_phone(item) for item in _PHONE_RE.findall(text)]
            found_addresses = [self._clean_address(item) for item in _ADDRESS_RE.findall(text)]
            page_social = [
                str(link.get("href") or "")
                for link in (page.get("links") or [])
                if any(token in str(link.get("href") or "").lower() for token in _SOCIAL_HINTS)
            ]

            if found_emails or found_phones or found_addresses:
                evidence_urls.append(page_url)
            if any(hint in page_url.lower() for hint in ("contact", "contacto", "reservas", "menu", "transparencia", "corporacion")):
                notes.append(f"Fuente prioritaria: {page_url}")

            emails.extend(found_emails)
            phones.extend(found_phones)
            addresses.extend(found_addresses)
            social_links.extend(page_social)

        merged_text = " ".join(all_text)
        source_url = str(pages[0].get("_page_url")) if pages and pages[0].get("_page_url") else website
        return {
            "name": self._infer_name(title, merged_text, domain),
            "website": website,
            "domain": domain,
            "emails": self._dedupe(emails),
            "phones": self._dedupe([item for item in phones if item]),
            "address": next((item for item in addresses if item), ""),
            "city": self._infer_city(merged_text),
            "province": self._infer_province(merged_text),
            "contact_form_only": not bool(emails) and self._contains_contact_form(merged_text),
            "social_links": self._dedupe(social_links),
            "source_url": source_url,
            "evidence_urls": self._dedupe(evidence_urls),
            "quality_signals": self._quality_signals(quality_signal_tokens, merged_text),
            "notes": notes,
        }

    def _resolve_obscura_binary(self) -> Path | None:
        candidate = Path(self.obscura_binary_path) if self.obscura_binary_path else _default_obscura_binary()
        return candidate if candidate.is_file() else None

    # ── httpx + BeautifulSoup: solo si el binario de Obscura no esta disponible ──

    async def _extract_via_httpx(
        self, website: str, link_hints: list[str], quality_signal_tokens: list[str]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        ) as client:
            try:
                base_response = await client.get(website)
                base_response.raise_for_status()
                base_html = base_response.text
            except Exception:
                return {
                    "source_url": website,
                    "evidence_urls": [],
                    "emails": [],
                    "phones": [],
                    "social_links": [],
                }

            pages = [(str(base_response.url), base_html)]
            for link in self._candidate_links(base_html, str(base_response.url), link_hints):
                if len(pages) >= self.max_pages_per_site:
                    break
                try:
                    response = await client.get(link)
                    response.raise_for_status()
                    pages.append((str(response.url), response.text))
                except Exception:
                    continue

        soup = BeautifulSoup(pages[0][1], "html.parser")
        title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
        all_text = []
        emails: list[str] = []
        phones: list[str] = []
        addresses: list[str] = []
        social_links: list[str] = []
        evidence_urls: list[str] = []
        notes: list[str] = []

        for page_url, html in pages:
            page_soup = BeautifulSoup(html, "html.parser")
            text = page_soup.get_text(" ", strip=True)
            all_text.append(text)

            found_emails = [item.lower() for item in _EMAIL_RE.findall(text)]
            found_phones = [self._clean_phone(item) for item in _PHONE_RE.findall(text)]
            found_addresses = [self._clean_address(item) for item in _ADDRESS_RE.findall(text)]
            page_social = [
                urljoin(page_url, anchor.get("href"))
                for anchor in page_soup.select("a[href]")
                if any(token in str(anchor.get("href") or "").lower() for token in _SOCIAL_HINTS)
            ]

            if found_emails or found_phones or found_addresses:
                evidence_urls.append(page_url)
            if any(hint in page_url.lower() for hint in ("contact", "contacto", "reservas", "menu", "transparencia", "corporacion")):
                notes.append(f"Fuente prioritaria: {page_url}")

            emails.extend(found_emails)
            phones.extend(found_phones)
            addresses.extend(found_addresses)
            social_links.extend(page_social)

        merged_text = " ".join(all_text)
        domain = (urlparse(website).hostname or "").lower()
        return {
            "name": self._infer_name(title, merged_text, domain),
            "website": website,
            "domain": domain,
            "emails": self._dedupe(emails),
            "phones": self._dedupe([item for item in phones if item]),
            "address": next((item for item in addresses if item), ""),
            "city": self._infer_city(merged_text),
            "province": self._infer_province(merged_text),
            "contact_form_only": not bool(emails) and self._contains_contact_form(merged_text),
            "social_links": self._dedupe(social_links),
            "source_url": pages[0][0],
            "evidence_urls": self._dedupe(evidence_urls),
            "quality_signals": self._quality_signals(quality_signal_tokens, merged_text),
            "notes": notes,
        }

    def _candidate_links(self, html: str, base_url: str, hints: list[str]) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "").strip()
            label = anchor.get_text(" ", strip=True).lower()
            if not href:
                continue
            low_href = href.lower()
            if any(hint in low_href or hint in label for hint in hints):
                links.append(urljoin(base_url, href))
        return self._dedupe(links)

    # ── Compartido ──────────────────────────────────────────────────────────

    def _infer_name(self, title: str, text: str, domain: str) -> str:
        if title:
            return title.split("|", 1)[0].split("·", 1)[0].strip()
        host = domain.split(".")[0]
        if host:
            return host.replace("-", " ").replace("_", " ").title()
        lines = [line.strip() for line in text.split(".") if line.strip()]
        return lines[0][:120] if lines else ""

    def _infer_city(self, text: str) -> str:
        match = re.search(r"\b(Madrid|Zaragoza|Salamanca|Toledo|Illescas|Alcalá de Henares|Torrejón de la Calzada)\b", text, re.IGNORECASE)
        return match.group(1) if match else ""

    def _infer_province(self, text: str) -> str:
        return self._infer_city(text)

    def _contains_contact_form(self, text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ("formulario", "contact form", "contacta con", "reservas online"))

    def _quality_signals(self, tokens: list[str], text: str) -> list[str]:
        lowered = text.lower()
        return [token for token in tokens if token in lowered]

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

    def _clean_phone(self, value: str) -> str:
        digits = re.sub(r"\D+", "", value)
        return digits[-9:] if len(digits) >= 9 else digits

    def _clean_address(self, value: str) -> str:
        return " ".join(value.split()).strip(" ,.;")

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            cleaned = str(item).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return result
