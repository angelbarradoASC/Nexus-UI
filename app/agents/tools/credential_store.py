"""
app/agents/tools/credential_store.py
--------------------------------------
Almacén local cifrado para credenciales SSH de servidores.

Cifrado  : Fernet (AES-128-CBC + HMAC-SHA256)
Derivación: PBKDF2-SHA256 desde CREDENTIAL_STORE_KEY
Escritura : atómica (tmp + rename) — nunca corrupción parcial

Formato de entrada:
    {
        "user": "admin",
        "password": "secreto",          # opcional si hay ssh_key_path
        "ssh_key_path": "/path/to/key", # opcional si hay password
        "port": 22,
        "auth_type": "password"         # "password" | "ssh_key"
    }
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from config import cfg

# Salt fijo — el secreto real es CREDENTIAL_STORE_KEY
_SALT = b"nexus-credential-store-v1"

# Campos obligatorios y validados al escribir
_CAMPOS_REQUERIDOS: tuple[str, ...] = ("user",)
_AUTH_TYPES: tuple[str, ...] = ("password", "ssh_key")


def _derivar_clave(raw_key: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(raw_key.encode()))


class CredentialStore:
    """
    Almacén cifrado de credenciales para acceso SSH.

    Thread-safe para lecturas concurrentes.
    Escritura atómica mediante fichero temporal + rename.
    """

    def __init__(self) -> None:
        raw_key = cfg.credential_store_key
        self._fernet = Fernet(_derivar_clave(raw_key))

        store_path = cfg.credential_store_path
        # En Docker el working dir es /app; en local puede ser relativo
        base = Path("/app") if Path("/app").exists() else Path(".")
        self._store_file = base / store_path
        self._store_file.parent.mkdir(parents=True, exist_ok=True)

        self._data: dict[str, dict[str, Any]] = self._cargar()
        logger.info(
            "CredentialStore inicializado | entradas={} | fichero={}",
            len(self._data),
            self._store_file,
        )

    # ── Interfaz pública ──────────────────────────────────────────────────────

    def get(self, hostname: str) -> dict[str, Any] | None:
        """Devuelve las credenciales de un host, o None si no existen."""
        return self._data.get(hostname)

    def set(self, hostname: str, creds: dict[str, Any]) -> None:
        """
        Guarda o sobreescribe las credenciales de un host.
        Valida campos obligatorios antes de guardar.
        """
        self._validar(hostname, creds)

        # Normalizar auth_type
        if "auth_type" not in creds:
            creds = dict(creds)  # no mutar el original
            creds["auth_type"] = "ssh_key" if creds.get("ssh_key_path") else "password"

        # Puerto por defecto
        creds.setdefault("port", 22)

        self._data[hostname] = creds
        self._guardar()
        logger.info("CredentialStore | credenciales guardadas | host={}", hostname)

    def delete(self, hostname: str) -> bool:
        """Elimina las credenciales de un host. True si existían."""
        if hostname in self._data:
            del self._data[hostname]
            self._guardar()
            logger.info("CredentialStore | credenciales eliminadas | host={}", hostname)
            return True
        return False

    def list_hosts(self) -> list[str]:
        """Lista los hostnames que tienen credenciales almacenadas."""
        return list(self._data.keys())

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _cargar(self) -> dict[str, dict[str, Any]]:
        """Carga y descifra el fichero de credenciales."""
        if not self._store_file.exists():
            return {}
        try:
            encrypted = self._store_file.read_bytes()
            plaintext = self._fernet.decrypt(encrypted)
            data = json.loads(plaintext.decode())
            logger.debug("CredentialStore cargado | entradas={}", len(data))
            return data
        except InvalidToken:
            logger.error(
                "CredentialStore: no se pudo descifrar. "
                "¿Ha cambiado CREDENTIAL_STORE_KEY? Iniciando vacío."
            )
            return {}
        except Exception as e:
            logger.error("CredentialStore: error cargando fichero | {}", e)
            return {}

    def _guardar(self) -> None:
        """
        Escritura atómica: cifra → escribe en .tmp → rename.
        Si el proceso cae a mitad, el fichero original no se corrompe.
        """
        tmp_file = self._store_file.with_suffix(".tmp")
        try:
            plaintext = json.dumps(self._data, ensure_ascii=False).encode()
            encrypted = self._fernet.encrypt(plaintext)
            tmp_file.write_bytes(encrypted)
            tmp_file.replace(self._store_file)  # atómico en mismo filesystem
        except Exception as e:
            logger.error("CredentialStore: error guardando | {}", e)
            # Limpiar tmp si quedó a medias
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)
            raise

    # ── Validación ────────────────────────────────────────────────────────────

    @staticmethod
    def _validar(hostname: str, creds: dict[str, Any]) -> None:
        if not hostname or not hostname.strip():
            raise ValueError("El hostname no puede estar vacío")

        for campo in _CAMPOS_REQUERIDOS:
            if not creds.get(campo):
                raise ValueError(f"Campo obligatorio faltante en credenciales: '{campo}'")

        auth_type = creds.get("auth_type")
        if auth_type and auth_type not in _AUTH_TYPES:
            raise ValueError(
                f"auth_type inválido: '{auth_type}'. "
                f"Valores permitidos: {_AUTH_TYPES}"
            )

        if auth_type == "ssh_key" and not creds.get("ssh_key_path"):
            raise ValueError("auth_type='ssh_key' requiere 'ssh_key_path'")

        port = creds.get("port", 22)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError(f"Puerto inválido: {port}")
