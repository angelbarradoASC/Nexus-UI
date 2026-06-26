"""Validation helpers for prospecting contact data."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import dns.exception
import dns.resolver

_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
_GENERIC_PREFIXES = {
    "info",
    "hola",
    "hello",
    "contact",
    "contacto",
    "reservas",
    "booking",
    "admin",
    "recepcion",
    "secretaria",
    "secretaria.general",
    "ayuntamiento",
}
_PERSONAL_DOMAINS = {
    "gmail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}


@dataclass(slots=True)
class EmailValidator:
    """Email classification focused on business prospecting."""

    def validate(self, email: str) -> dict[str, Any]:
        value = (email or "").strip().lower()
        domain = value.split("@", 1)[1] if "@" in value else ""
        local = value.split("@", 1)[0] if "@" in value else ""
        return {
            "email": value,
            "format_valid": bool(_EMAIL_RE.match(value)),
            "domain": domain,
            "is_generic": local in _GENERIC_PREFIXES,
            "is_personal": domain in _PERSONAL_DOMAINS,
        }


@dataclass(slots=True)
class DomainValidator:
    """DNS A/AAAA validation."""

    async def validate(self, domain: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._resolve, domain, "A")

    def _resolve(self, domain: str, record_type: str) -> dict[str, Any]:
        resolver = dns.resolver.Resolver()
        domain = (domain or "").strip().lower()
        if not domain:
            return {"domain": "", "dns_valid": False}
        try:
            resolver.resolve(domain, record_type)
            return {"domain": domain, "dns_valid": True}
        except dns.exception.DNSException:
            try:
                resolver.resolve(domain, "AAAA")
                return {"domain": domain, "dns_valid": True}
            except dns.exception.DNSException:
                return {"domain": domain, "dns_valid": False}


@dataclass(slots=True)
class MXValidator:
    """MX validation."""

    async def validate(self, domain: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._resolve, domain)

    def _resolve(self, domain: str) -> dict[str, Any]:
        resolver = dns.resolver.Resolver()
        domain = (domain or "").strip().lower()
        if not domain:
            return {"domain": "", "mx_valid": False}
        try:
            answer = resolver.resolve(domain, "MX")
            return {
                "domain": domain,
                "mx_valid": True,
                "hosts": [str(item.exchange).rstrip(".") for item in answer],
            }
        except dns.exception.DNSException:
            return {"domain": domain, "mx_valid": False, "hosts": []}
