"""SMTP and IMAP helpers for the outreach agent."""

from __future__ import annotations

import imaplib
import smtplib
import ssl
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any


class SMTPOutreachTransport:
    """Minimal SMTP sender over SSL/TLS."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        timeout_seconds: int = 15,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds

    def configured(self) -> bool:
        return bool(self._host and self._port and self._username and self._password)

    def send(self, message: EmailMessage) -> dict[str, Any]:
        if not self.configured():
            return {"status": "not_configured"}
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            self._host,
            self._port,
            timeout=self._timeout_seconds,
            context=context,
        ) as server:
            server.login(self._username, self._password)
            server.send_message(message)
        return {"status": "sent"}

    def healthcheck(self) -> dict[str, Any]:
        if not self.configured():
            return {"configured": False, "status": "not_configured"}
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            self._host,
            self._port,
            timeout=self._timeout_seconds,
            context=context,
        ) as server:
            server.login(self._username, self._password)
            server.noop()
        return {"configured": True, "status": "up"}


class IMAPMailboxMonitor:
    """Very small IMAP monitor for connectivity and unread count."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        timeout_seconds: int = 15,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds

    def configured(self) -> bool:
        return bool(self._host and self._port and self._username and self._password)

    def healthcheck(self) -> dict[str, Any]:
        if not self.configured():
            return {"configured": False, "status": "not_configured"}
        client = imaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout_seconds)
        try:
            client.login(self._username, self._password)
            status, _ = client.select("INBOX")
            unread_status, unread_data = client.search(None, "UNSEEN")
            unread_count = 0
            if unread_status == "OK" and unread_data and unread_data[0]:
                unread_count = len(unread_data[0].split())
            return {"configured": True, "status": "up" if status == "OK" else "degraded", "unread_count": unread_count}
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def find_replies(self, *, from_addresses: list[str], since: datetime) -> dict[str, str]:
        """Busca en INBOX mensajes recibidos DESPUES de `since` cuyo
        remitente coincida con alguno de from_addresses (prospectos ya
        contactados). Devuelve {email: received_at_iso} solo para
        coincidencias con fecha real posterior a `since` — IMAP SINCE es
        granularidad de dia, así que se filtra la fecha exacta de la
        cabecera para no dar falsos positivos del mismo dia."""
        if not self.configured() or not from_addresses:
            return {}
        replies: dict[str, str] = {}
        client = imaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout_seconds)
        try:
            client.login(self._username, self._password)
            client.select("INBOX")
            since_imap = since.strftime("%d-%b-%Y")
            for address in from_addresses:
                status, data = client.search(None, f'(FROM "{address}" SINCE "{since_imap}")')
                if status != "OK" or not data or not data[0]:
                    continue
                for msg_id in reversed(data[0].split()):
                    _, hdr_data = client.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (DATE)])")
                    received_at = self._extract_header_date(hdr_data)
                    if received_at and received_at > since:
                        replies[address] = received_at.isoformat()
                        break
            return replies
        finally:
            try:
                client.logout()
            except Exception:
                pass

    @staticmethod
    def _extract_header_date(hdr_data: Any) -> datetime | None:
        for part in hdr_data:
            if not isinstance(part, tuple):
                continue
            message = message_from_bytes(part[1])
            raw = message.get("Date")
            if not raw:
                continue
            try:
                dt = parsedate_to_datetime(raw)
            except Exception:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        return None
