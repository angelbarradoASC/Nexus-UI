"""Thunderbird mailbox discovery, reading and prioritization."""

from __future__ import annotations

import asyncio
import base64
import ctypes
import imaplib
import json
import os
import quopri
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Any

from agents.llm_router import LLMRouter
from nexus.prompts import resolve_prompt_sync
from nexus.utils.llm_json import strip_llm_fences


@dataclass
class ThunderbirdAccount:
    email: str
    full_name: str
    username: str
    host: str
    port: int
    folder_uri: str
    folder_name: str


class _SECItem(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint),
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("len", ctypes.c_uint),
    ]


class ThunderbirdCredentialStore:
    """Decrypts Thunderbird saved credentials through NSS."""

    def __init__(self, profile_dir: Path, install_dir: Path | None = None) -> None:
        self.profile_dir = profile_dir
        self.install_dir = install_dir
        self._dll_dir: Path | None = None
        self._nss = None

    def decrypt_login(self, encrypted_username: str, encrypted_password: str) -> tuple[str, str]:
        self._ensure_nss()
        return (
            self._decrypt_sdr(encrypted_username),
            self._decrypt_sdr(encrypted_password),
        )

    def _ensure_nss(self) -> None:
        if self._nss is not None:
            return
        if self.install_dir is not None and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(self.install_dir))
        nss = ctypes.CDLL("nss3.dll")
        nss.NSS_Init.argtypes = [ctypes.c_char_p]
        nss.NSS_Init.restype = ctypes.c_int
        nss.PK11SDR_Decrypt.argtypes = [
            ctypes.POINTER(_SECItem),
            ctypes.POINTER(_SECItem),
            ctypes.c_void_p,
        ]
        nss.PK11SDR_Decrypt.restype = ctypes.c_int
        nss.SECITEM_FreeItem.argtypes = [ctypes.POINTER(_SECItem), ctypes.c_int]
        rc = nss.NSS_Init(str(self.profile_dir).encode("utf-8"))
        if rc != 0:
            raise RuntimeError(f"NSS_Init failed with code {rc}")
        self._nss = nss

    def _decrypt_sdr(self, encrypted_value: str) -> str:
        raw = base64.b64decode(encrypted_value)
        buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        input_item = _SECItem(0, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)), len(raw))
        output_item = _SECItem()
        rc = self._nss.PK11SDR_Decrypt(ctypes.byref(input_item), ctypes.byref(output_item), None)
        if rc != 0:
            raise RuntimeError(f"PK11SDR_Decrypt failed with code {rc}")
        try:
            data = ctypes.string_at(output_item.data, output_item.len)
            return data.decode("utf-8")
        finally:
            self._nss.SECITEM_FreeItem(ctypes.byref(output_item), 0)


class ThunderbirdMailManager:
    """Reads Thunderbird-configured accounts and surfaces priority inbox items."""

    def __init__(self, cfg, llm_router: LLMRouter | None = None, now_fn=None) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # ── API publica ─────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        if not self._cfg.thunderbird_enabled:
            return {"status": "disabled", "reason": "Thunderbird local desactivado en esta instancia."}
        profile_dir = self._resolve_profile_dir()
        if profile_dir is None:
            return {"status": "not_configured", "reason": "No se encontro un perfil valido de Thunderbird."}
        accounts = self._discover_accounts(profile_dir)
        preferred = self._preferred_accounts()
        return {
            "status": "success",
            "profile_dir": str(profile_dir),
            "accounts": [
                {
                    "email": a.email,
                    "full_name": a.full_name,
                    "host": a.host,
                    "folder_name": a.folder_name,
                    "priority": (a.email.lower() in preferred) if preferred else True,
                }
                for a in accounts
            ],
            "account_count": len(accounts),
        }

    async def get_priority_messages(self, limit: int | None = None) -> dict[str, Any]:
        if not self._cfg.thunderbird_enabled:
            return {"status": "disabled", "messages": []}
        profile_dir = self._resolve_profile_dir()
        if profile_dir is None:
            return {"status": "not_configured", "messages": []}

        accounts = self._discover_accounts(profile_dir)
        preferred = self._preferred_accounts()
        if preferred:
            accounts = [a for a in accounts if a.email.lower() in preferred]

        store = ThunderbirdCredentialStore(
            profile_dir,
            Path(self._cfg.thunderbird_install_dir) if self._cfg.thunderbird_install_dir else None,
        )
        logins = self._load_logins(profile_dir)

        limit_per_account = int(self._cfg.thunderbird_message_limit_per_account)
        results = await asyncio.gather(
            *(
                asyncio.to_thread(self._fetch_account_messages, account, store, logins, limit_per_account)
                for account in accounts
            ),
            return_exceptions=True,
        )

        messages: list[dict[str, Any]] = []
        for account, result in zip(accounts, results):
            if isinstance(result, Exception):
                messages.append({"account_email": account.email, "error": str(result)})
                continue
            messages.extend(result)

        if self._llm_router is not None and messages:
            try:
                messages = await self._enrich_with_llm(messages)
            except Exception:
                pass

        messages.sort(key=lambda m: (m.get("priority_score", 0), m.get("received_at", "")), reverse=True)
        total_limit = int(limit) if limit is not None else int(self._cfg.thunderbird_priority_total_limit)
        return {
            "status": "success",
            "messages": messages[:total_limit],
            "checked_at": self._now_fn().isoformat(),
        }

    # ── Descubrimiento de perfil y cuentas ──────────────────────────────────

    def _resolve_profile_dir(self) -> Path | None:
        if self._cfg.thunderbird_profile_name and self._cfg.thunderbird_profile_root:
            candidate = Path(self._cfg.thunderbird_profile_root) / "Profiles" / self._cfg.thunderbird_profile_name
            if candidate.exists():
                return candidate.resolve()

        if self._cfg.thunderbird_profile_root:
            root = Path(self._cfg.thunderbird_profile_root)
        else:
            root = Path(os.environ.get("APPDATA", "")) / "Thunderbird"

        profiles_ini = root / "profiles.ini"
        if not profiles_ini.exists():
            return None

        sections: dict[str, dict[str, str]] = {}
        current: str | None = None
        for raw_line in profiles_ini.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
                sections[current] = {}
            elif current and "=" in line:
                key, _, value = line.partition("=")
                sections[current][key.strip()] = value.strip()

        default_name = next(
            (v.get("Default") for k, v in sections.items() if k.startswith("Install") and v.get("Default")),
            None,
        )
        if not default_name:
            default_name = next(
                (v.get("Path") for k, v in sections.items() if k.startswith("Profile") and v.get("Default") == "1"),
                None,
            )

        if default_name:
            candidate = root / default_name
            if candidate.exists():
                return candidate.resolve()

        for key, section in sections.items():
            if key.startswith("Profile") and section.get("Path"):
                candidate = root / section["Path"]
                if candidate.exists():
                    return candidate.resolve()

        return None

    def _discover_accounts(self, profile_dir: Path) -> list[ThunderbirdAccount]:
        prefs = self._parse_prefs(profile_dir / "prefs.js")
        account_ids = [a.strip() for a in str(prefs.get("mail.accountmanager.accounts", "")).split(",") if a.strip()]

        accounts: list[ThunderbirdAccount] = []
        for account_id in account_ids:
            server_id = prefs.get(f"mail.account.{account_id}.server")
            if not server_id:
                continue
            server_type = prefs.get(f"mail.server.{server_id}.type")
            if server_type != "imap":
                continue

            identity_ids = [
                i.strip()
                for i in str(prefs.get(f"mail.account.{account_id}.identities", "")).split(",")
                if i.strip()
            ]
            identity_id = identity_ids[0] if identity_ids else None
            email = prefs.get(f"mail.identity.{identity_id}.useremail") if identity_id else None
            if not email:
                continue

            host = prefs.get(f"mail.server.{server_id}.hostname", "")
            port = int(prefs.get(f"mail.server.{server_id}.port", 993) or 993)
            full_name = prefs.get(f"mail.identity.{identity_id}.fullName", "") if identity_id else ""
            username = prefs.get(f"mail.server.{server_id}.userName", email)
            folder_uri = f"imap://{email.replace('@', '%40')}@{host}/INBOX"

            accounts.append(
                ThunderbirdAccount(
                    email=email,
                    full_name=full_name,
                    username=username,
                    host=host,
                    port=port,
                    folder_uri=folder_uri,
                    folder_name="INBOX",
                )
            )
        return accounts

    def _parse_prefs(self, prefs_path: Path) -> dict[str, Any]:
        if not prefs_path.exists():
            return {}
        pattern = re.compile(r'user_pref\("([^"]+)",\s*(.+?)\);')
        prefs: dict[str, Any] = {}
        for raw_line in prefs_path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(raw_line.strip())
            if not match:
                continue
            key, raw_value = match.groups()
            raw_value = raw_value.strip()
            if raw_value == "true":
                prefs[key] = True
            elif raw_value == "false":
                prefs[key] = False
            elif raw_value.startswith('"') and raw_value.endswith('"'):
                try:
                    prefs[key] = json.loads(raw_value)
                except ValueError:
                    prefs[key] = raw_value.strip('"')
            else:
                try:
                    prefs[key] = int(raw_value)
                except ValueError:
                    prefs[key] = raw_value
        return prefs

    def _preferred_accounts(self) -> set[str]:
        raw = str(self._cfg.thunderbird_priority_accounts or "")
        return {a.strip().lower() for a in raw.split(",") if a.strip()}

    def _load_logins(self, profile_dir: Path) -> list[dict[str, Any]]:
        path = profile_dir / "logins.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("logins", []))

    # ── IMAP (sincrono, corre en to_thread) ─────────────────────────────────

    def _fetch_account_messages(
        self,
        account: ThunderbirdAccount,
        store: ThunderbirdCredentialStore,
        logins: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        username, password = self._resolve_credentials(account, store, logins)
        conn = imaplib.IMAP4_SSL(account.host, account.port)
        try:
            conn.login(username, password)
            conn.select("INBOX")
            _, data = conn.search(None, "ALL")
            ids = data[0].split() if data and data[0] else []
            ids = list(reversed(ids))[:limit]

            messages: list[dict[str, Any]] = []
            for msg_id in ids:
                _, msg_data = conn.fetch(
                    msg_id,
                    "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.700>)",
                )
                parsed = self._parse_imap_message(account, msg_id, msg_data)
                if parsed:
                    messages.append(parsed)
            return messages
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _resolve_credentials(
        self,
        account: ThunderbirdAccount,
        store: ThunderbirdCredentialStore,
        logins: list[dict[str, Any]],
    ) -> tuple[str, str]:
        match = next(
            (entry for entry in logins if account.host.lower() in str(entry.get("hostname", "")).lower()),
            None,
        )
        if match is None:
            raise RuntimeError(f"No se encontraron credenciales de Thunderbird para {account.email}")
        try:
            username, password = store.decrypt_login(match["encryptedUsername"], match["encryptedPassword"])
        except Exception as exc:
            raise RuntimeError(f"No se pudieron descifrar credenciales para {account.email}") from exc
        return username or account.username, password

    def _parse_imap_message(self, account: ThunderbirdAccount, msg_id: bytes, msg_data: list[Any]) -> dict[str, Any] | None:
        raw_headers = None
        raw_body = b""
        flags_text = ""

        for part in msg_data:
            if isinstance(part, tuple):
                meta, content = part
                meta_str = meta.decode("utf-8", "ignore") if isinstance(meta, (bytes, bytearray)) else str(meta)
                if "HEADER.FIELDS" in meta_str:
                    raw_headers = content
                elif "BODY[TEXT]" in meta_str:
                    raw_body = content or b""
                if "FLAGS" in meta_str:
                    flags_text = meta_str
            elif isinstance(part, (bytes, bytearray)):
                flags_text += part.decode("utf-8", "ignore")

        if raw_headers is None:
            return None

        message = message_from_bytes(raw_headers)
        sender_name, sender_email = parseaddr(message.get("From", ""))
        sender_name = self._decode_header_value(sender_name)
        subject = self._decode_header_value(message.get("Subject", "")) or "(sin asunto)"
        received_at = self._normalize_date(message.get("Date", ""))

        unread = "\\Seen" not in flags_text
        flagged = "\\Flagged" in flags_text
        preview = self._extract_preview(raw_body)
        score = self._score_message(sender_email, subject, preview)

        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
        return {
            "message_id": f"{account.email}:{msg_id_str}",
            "account_email": account.email,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": subject,
            "preview": preview,
            "received_at": received_at,
            "unread": unread,
            "flagged": flagged,
            "priority_score": score,
            "importance": self._importance_from_score(score),
            "reason": "Calificacion heuristica inicial",
            "suggested_action": "leer",
        }

    @staticmethod
    def _score_message(sender_email: str, subject: str, preview: str) -> int:
        text = f"{subject} {preview}".lower()
        score = 50
        if "newsletter" in text or "unsubscribe" in text or "suscrib" in text:
            score -= 30
        return max(0, min(100, score))

    async def _enrich_with_llm(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system_prompt = resolve_prompt_sync("mail.qualification")
        payload = [
            {
                "message_id": m["message_id"],
                "account_email": m["account_email"],
                "sender_name": m["sender_name"],
                "sender_email": m["sender_email"],
                "subject": m["subject"],
                "preview": m["preview"],
                "unread": m["unread"],
                "flagged": m["flagged"],
                "priority_score": m["priority_score"],
            }
            for m in messages
            if "error" not in m
        ]
        if not payload:
            return messages

        response = await self._llm_router.call(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if response.error:
            raise RuntimeError(response.error)

        content = strip_llm_fences(response.content)
        try:
            qualified = json.loads(content)
        except json.JSONDecodeError:
            return messages

        by_id = {item.get("message_id"): item for item in qualified if isinstance(item, dict)}
        for m in messages:
            update = by_id.get(m.get("message_id"))
            if not update:
                continue
            m["priority_score"] = int(update.get("score", m.get("priority_score", 0)))
            m["importance"] = update.get("importance", m.get("importance"))
            m["reason"] = update.get("reason", m.get("reason"))
            m["suggested_action"] = update.get("suggested_action", m.get("suggested_action"))
        return messages

    @staticmethod
    def _importance_from_score(score: int) -> str:
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"

    @staticmethod
    def _decode_header_value(value: str | None) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @staticmethod
    def _normalize_date(value: str | None) -> str | None:
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return None

    @staticmethod
    def _extract_preview(body_bytes: bytes) -> str:
        text = ThunderbirdMailManager._decode_body_snippet(body_bytes)
        text = ThunderbirdMailManager._strip_transport_garbage(text)
        text = ThunderbirdMailManager._strip_reply_noise(text)
        text = re.sub(r"\s+", " ", text).strip(" -\n\r\t")
        return text

    @staticmethod
    def _decode_body_snippet(body_bytes: bytes) -> str:
        if not body_bytes:
            return ""
        text_guess = body_bytes.decode("utf-8", "ignore")
        match = re.search(r"^content-transfer-encoding:\s*(.+)$", text_guess, re.IGNORECASE | re.MULTILINE)
        encoding = match.group(1).strip().lower() if match else ""

        raw = body_bytes
        try:
            if "quoted-printable" in encoding:
                raw = quopri.decodestring(raw)
            elif "base64" in encoding:
                clean = raw.replace(b"\n", b"").replace(b"\r", b"")
                idx = clean.find(b"\r\n\r\n")
                if idx != -1:
                    clean = clean[idx + 4 :]
                clean += b"=" * (-len(clean) % 4)
                raw = base64.b64decode(clean)
        except Exception:
            pass
        return raw.decode("utf-8", "ignore")

    @staticmethod
    def _strip_transport_garbage(text: str) -> str:
        text = re.sub(r"=\s*$", "", text, flags=re.MULTILINE)
        patterns = [
            r"^--[-\w.]+.*$",
            r'^\s*boundary\s*=\s*"?[^"\n]{0,120}"?\s*$',
            r"^(MIME-Version|Content-Type|Content-Transfer-Encoding|Content-Disposition):.*$",
            r"^\s+(boundary|charset|name|filename)\s*=.*$",
            r"^[A-Za-z0-9+/]{60,}={0,2}\s*$",
            r"^\[[^\]]+\]\s*$",
            r"^\s*https?://\S+\s*$",
            r"^cid:\S+\s*$",
            r"^-?enmime-[\w-]+.*$",
            r"^\s*charset\s*=\s*[-\w.]+\s*$",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.MULTILINE | re.IGNORECASE)
        text = re.sub(r"=\s{0,2}([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r"\[https?://[^\]]+\]", "", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    @staticmethod
    def _strip_reply_noise(text: str) -> str:
        kept: list[str] = []
        for line in text.splitlines():
            lowered = line.strip().lower()
            if lowered.startswith(("from:", "sent:", "to:", "subject:")):
                break
            if lowered.startswith("el ") and "escribi" in lowered:
                break
            if lowered.startswith("on ") and "wrote:" in lowered:
                break
            if lowered.startswith("-- "):
                break
            kept.append(line)
        return "\n".join(kept).strip()
