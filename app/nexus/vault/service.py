"""
app/nexus/vault/service.py
----------------------------
VaultService — almacenamiento cifrado de credenciales de gestión.

Principios de seguridad:
  - Las credenciales (passwords, SSH keys) se cifran con Fernet (AES-128-CBC + HMAC)
  - La clave Fernet se deriva de una master_password con PBKDF2-HMAC-SHA256
  - El vault arranca BLOQUEADO. Ninguna credencial es accesible hasta que
    se llame a unlock(master_password).
  - La clave derivada vive solo en memoria. Nunca se escribe a disco.
  - El LLM nunca recibe credenciales en claro. VaultService solo entrega
    el objeto `Credential` al conector SSH/WinRM, que lo consume internamente.

Almacenamiento:
  - SQLite en data/vault/vault.db
  - Tabla `credentials`: cred_id, device_id, auth_method, username,
    encrypted_secret (Fernet), encrypted_ssh_key (Fernet, opcional)
  - Tabla `vault_meta`: salt del PBKDF2, verificador de contraseña
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# ── Modelos ───────────────────────────────────────────────────────────────────

@dataclass
class Credential:
    cred_id:        str
    device_id:      str
    auth_method:    str   # password | ssh_key | api_token
    username:       str
    secret:         str   # password o API token (en claro — solo en memoria mientras se usa)
    ssh_key:        str | None = None  # PEM key (en claro — solo en memoria)
    created_at:     str = ""
    updated_at:     str = ""

    def to_dict(self, redact: bool = True) -> dict[str, Any]:
        return {
            "cred_id":     self.cred_id,
            "device_id":   self.device_id,
            "auth_method": self.auth_method,
            "username":    self.username,
            "secret":      "***" if redact else self.secret,
            "has_ssh_key": self.ssh_key is not None,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
        }


# ── VaultService ──────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credentials (
    cred_id          TEXT PRIMARY KEY,
    device_id        TEXT NOT NULL,
    auth_method      TEXT NOT NULL,
    username         TEXT NOT NULL,
    encrypted_secret TEXT NOT NULL,
    encrypted_ssh_key TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cred_device ON credentials(device_id);
"""

_PBKDF2_ITERATIONS = 480_000


class VaultService:
    """
    Vault de credenciales cifradas para NEXUS.

    Uso:
        vault = VaultService()
        await vault.setup("mi-master-password")   # primera vez
        await vault.unlock("mi-master-password")  # al arrancar
        cred = await vault.get_credential("dev-abc123")
        # → cred.secret está en claro solo mientras se usa
    """

    def __init__(self, db_path: str | Path = "data/vault/vault.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet: Fernet | None = None
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Estado del vault ──────────────────────────────────────────────────────

    @property
    def is_locked(self) -> bool:
        return self._fernet is None

    @property
    def is_initialized(self) -> bool:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT value FROM vault_meta WHERE key='salt'"
            ).fetchone()
            return row is not None

    # ── Setup / Unlock / Lock ─────────────────────────────────────────────────

    async def setup(self, master_password: str) -> None:
        """Primera vez: establece la master password y genera el salt."""
        if self.is_initialized:
            raise RuntimeError("El vault ya está inicializado. Usa unlock().")

        def _init():
            salt = os.urandom(32)
            fernet_key = self._derive_key(master_password, salt)
            # Guardar el verificador (token cifrado de una cadena conocida)
            f = Fernet(fernet_key)
            verifier = f.encrypt(b"nexus-vault-v1")
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO vault_meta VALUES (?,?)",
                    ("salt", base64.b64encode(salt).decode()),
                )
                conn.execute(
                    "INSERT INTO vault_meta VALUES (?,?)",
                    ("verifier", verifier.decode()),
                )
                conn.commit()
            return fernet_key

        fernet_key = await asyncio.to_thread(_init)
        self._fernet = Fernet(fernet_key)

    async def unlock(self, master_password: str) -> bool:
        """Desbloquea el vault. Devuelve False si la contraseña es incorrecta."""
        def _try_unlock():
            with sqlite3.connect(self._path) as conn:
                salt_row = conn.execute(
                    "SELECT value FROM vault_meta WHERE key='salt'"
                ).fetchone()
                verifier_row = conn.execute(
                    "SELECT value FROM vault_meta WHERE key='verifier'"
                ).fetchone()
            if not salt_row or not verifier_row:
                return None
            salt = base64.b64decode(salt_row[0])
            fernet_key = self._derive_key(master_password, salt)
            f = Fernet(fernet_key)
            try:
                f.decrypt(verifier_row[0].encode())
                return fernet_key
            except InvalidToken:
                return None

        fernet_key = await asyncio.to_thread(_try_unlock)
        if fernet_key is None:
            return False
        self._fernet = Fernet(fernet_key)
        return True

    def lock(self) -> None:
        """Bloquea el vault. La clave desaparece de memoria."""
        self._fernet = None

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def _require_unlocked(self) -> Fernet:
        if self._fernet is None:
            raise PermissionError("El vault está bloqueado. Llama a unlock() primero.")
        return self._fernet

    # ── CRUD de credenciales ──────────────────────────────────────────────────

    async def store(
        self,
        device_id:   str,
        auth_method: str,
        username:    str,
        secret:      str,
        ssh_key:     str | None = None,
    ) -> Credential:
        """Cifra y almacena credenciales para un dispositivo."""
        f = self._require_unlocked()

        def _write():
            cred_id  = f"cred-{uuid.uuid4().hex[:10]}"
            enc_sec  = f.encrypt(secret.encode()).decode()
            enc_key  = f.encrypt(ssh_key.encode()).decode() if ssh_key else None
            now      = self._now()
            with sqlite3.connect(self._path) as conn:
                # Si ya existe una credencial para este device_id, la reemplaza
                old = conn.execute(
                    "SELECT cred_id FROM credentials WHERE device_id=?", (device_id,)
                ).fetchone()
                if old:
                    conn.execute(
                        """UPDATE credentials SET auth_method=?, username=?,
                           encrypted_secret=?, encrypted_ssh_key=?, updated_at=?
                           WHERE device_id=?""",
                        (auth_method, username, enc_sec, enc_key, now, device_id),
                    )
                    cred_id = old[0]
                else:
                    conn.execute(
                        """INSERT INTO credentials VALUES (?,?,?,?,?,?,?,?)""",
                        (cred_id, device_id, auth_method, username, enc_sec, enc_key, now, now),
                    )
                conn.commit()
            return cred_id, now

        cred_id, now = await asyncio.to_thread(_write)
        return Credential(
            cred_id=cred_id,
            device_id=device_id,
            auth_method=auth_method,
            username=username,
            secret=secret,
            ssh_key=ssh_key,
            created_at=now,
            updated_at=now,
        )

    async def get_credential(self, device_id: str) -> Credential | None:
        """Descifra y devuelve las credenciales de un dispositivo."""
        f = self._require_unlocked()

        def _read():
            with sqlite3.connect(self._path) as conn:
                row = conn.execute(
                    """SELECT cred_id, device_id, auth_method, username,
                              encrypted_secret, encrypted_ssh_key, created_at, updated_at
                       FROM credentials WHERE device_id=?""",
                    (device_id,),
                ).fetchone()
            return row

        row = await asyncio.to_thread(_read)
        if not row:
            return None

        cred_id, dev_id, auth_method, username, enc_sec, enc_key, created_at, updated_at = row
        secret  = f.decrypt(enc_sec.encode()).decode()
        ssh_key = f.decrypt(enc_key.encode()).decode() if enc_key else None

        return Credential(
            cred_id=cred_id,
            device_id=dev_id,
            auth_method=auth_method,
            username=username,
            secret=secret,
            ssh_key=ssh_key,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def delete_credential(self, device_id: str) -> bool:
        def _del():
            with sqlite3.connect(self._path) as conn:
                n = conn.execute(
                    "DELETE FROM credentials WHERE device_id=?", (device_id,)
                ).rowcount
                conn.commit()
            return n > 0
        return await asyncio.to_thread(_del)

    async def list_credential_stubs(self) -> list[dict[str, Any]]:
        """Lista de credenciales SIN descifrar — solo metadatos. Para la UI."""
        def _list():
            with sqlite3.connect(self._path) as conn:
                rows = conn.execute(
                    """SELECT cred_id, device_id, auth_method, username,
                              encrypted_ssh_key IS NOT NULL, created_at, updated_at
                       FROM credentials"""
                ).fetchall()
            return rows
        rows = await asyncio.to_thread(_list)
        return [
            {
                "cred_id":     r[0],
                "device_id":   r[1],
                "auth_method": r[2],
                "username":    r[3],
                "has_ssh_key": bool(r[4]),
                "created_at":  r[5],
                "updated_at":  r[6],
            }
            for r in rows
        ]
