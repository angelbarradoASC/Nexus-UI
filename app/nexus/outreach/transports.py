"""SMTP and IMAP helpers for the outreach agent."""

from __future__ import annotations

import imaplib
import smtplib
import ssl
from email.message import EmailMessage
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
