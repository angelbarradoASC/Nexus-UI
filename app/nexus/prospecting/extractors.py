"""Website extraction helpers for prospecting candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

_PHONE_RE = re.compile(r"(?:\+34\s*)?(?:\d[\s().-]?){9,14}")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_ADDRESS_RE = re.compile(r"(?:calle|plaza|avenida|avda|paseo|c\\/|c\\.)\s+[^\n,]{4,}", re.IGNORECASE)
_SOCIAL_HINTS = ("instagram.com", "facebook.com", "linkedin.com", "tripadvisor.", "thefork.", "google.")
_PUBLIC_LINK_HINTS = ("contacto", "contact", "corporacion", "corporación", "concejal", "transparencia", "secretaria", "equipo")
_RESTAURANT_LINK_HINTS = ("contacto", "contact", "reservas", "reservation", "menu", "carta", "eventos", "about", "legal")


_JINA_BASE = "https://r.jina.ai"
_MIN_USEFUL_CHARS = 300  # below this we try Jina Reader as fallback


@dataclass(slots=True)
class WebProspectExtractor:
    timeout_seconds: float = 12.0
    user_agent: str = "Open-Nexus Prospecting/1.0"
    max_pages_per_site: int = 4
    use_jina_fallback: bool = True  # free JS-render fallback via Jina Reader API

    async def extract(self, *, url: str, vertical: str) -> dict[str, Any]:
        website = self._normalize_url(url)
        if not website:
            return {"source_url": "", "evidence_urls": [], "emails": [], "phones": [], "social_links": []}

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
                # httpx failed — try Jina Reader directly as the only source
                jina_text = await self._jina_fetch(website) if self.use_jina_fallback else ""
                if jina_text:
                    return self._extract_from_plain_text(jina_text, website, source="jina")
                return {
                    "source_url": website,
                    "evidence_urls": [],
                    "emails": [],
                    "phones": [],
                    "social_links": [],
                }

            # If the page returned very little usable text (JS-only render), use Jina
            plain_preview = BeautifulSoup(base_html, "html.parser").get_text(" ", strip=True)
            if self.use_jina_fallback and len(plain_preview) < _MIN_USEFUL_CHARS:
                jina_text = await self._jina_fetch(website)
                if jina_text and len(jina_text) > len(plain_preview):
                    return self._extract_from_plain_text(jina_text, website, source="jina")

            pages = [(str(base_response.url), base_html)]
            for link in self._candidate_links(base_html, str(base_response.url), vertical):
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
            "quality_signals": self._quality_signals(vertical, merged_text),
            "notes": notes,
        }

    def _candidate_links(self, html: str, base_url: str, vertical: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        hints = _PUBLIC_LINK_HINTS if vertical == "public_administration" else _RESTAURANT_LINK_HINTS
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

    def _quality_signals(self, vertical: str, text: str) -> list[str]:
        lowered = text.lower()
        if vertical == "restaurants":
            tokens = (
                "menu degustacion",
                "eventos",
                "grupos",
                "terraza",
                "reservas",
                "tripadvisor",
                "thefork",
                "instagram",
                "cena de empresa",
            )
        else:
            tokens = (
                "administracion electronica",
                "sede electronica",
                "nuevas tecnologias",
                "transformacion digital",
                "modernizacion",
                "transparencia",
            )
        return [token for token in tokens if token in lowered]

    async def _jina_fetch(self, url: str) -> str:
        """Fetch a JS-rendered page via Jina Reader (free, no API key)."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{_JINA_BASE}/{url}",
                    headers={"User-Agent": self.user_agent, "Accept": "text/plain"},
                )
                if resp.status_code == 200:
                    return resp.text
        except Exception:
            pass
        return ""

    def _extract_from_plain_text(
        self, text: str, website: str, *, source: str = "jina"
    ) -> dict[str, Any]:
        """Extract contact signals from plain/markdown text (Jina Reader output)."""
        domain = (urlparse(website).hostname or "").lower()
        emails = self._dedupe([item.lower() for item in _EMAIL_RE.findall(text)])
        phones = self._dedupe([self._clean_phone(item) for item in _PHONE_RE.findall(text)])
        addresses = self._dedupe([self._clean_address(item) for item in _ADDRESS_RE.findall(text)])
        # Infer name from first non-empty line of the markdown text
        first_line = next((ln.strip().lstrip("#").strip() for ln in text.splitlines() if ln.strip()), "")
        return {
            "name": first_line[:120] if first_line else domain,
            "website": website,
            "domain": domain,
            "emails": emails,
            "phones": [p for p in phones if p],
            "address": addresses[0] if addresses else "",
            "city": self._infer_city(text),
            "province": self._infer_province(text),
            "contact_form_only": not bool(emails) and self._contains_contact_form(text),
            "social_links": [],
            "source_url": website,
            "evidence_urls": [website] if (emails or phones) else [],
            "quality_signals": self._quality_signals("custom", text),
            "notes": [f"Fuente: Jina Reader ({source})"] if (emails or phones) else [],
        }

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
