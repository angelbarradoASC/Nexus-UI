"""Mailbox intelligence for Nexus — Thunderbird (local) y Outlook (Graph)."""

from .outlook import OutlookAuthError, OutlookMailManager
from .outlook_reply_agent import OutlookReplyAgent
from .service import ThunderbirdMailManager

__all__ = ["ThunderbirdMailManager", "OutlookMailManager", "OutlookAuthError", "OutlookReplyAgent"]
