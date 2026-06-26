"""
app/utils/session_auth.py
--------------------------
Gestión de sesiones web con TTL + autenticación bcrypt.

Responsabilidades:
  - Hashear contraseñas con bcrypt al arrancar
  - Verificar contraseñas con bcrypt.checkpw (timing-safe)
  - Crear/verificar/cerrar sesiones con expiración automática
  - Limpiar sesiones expiradas periódicamente

Uso:
    from utils.session_auth import SessionAuth
    auth = SessionAuth(cfg)          # singleton en main.py
    token = auth.crear_sesion("admin")
    username = auth.verificar_sesion(token)  # None si expirada
    auth.cerrar_sesion(token)
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import bcrypt
from loguru import logger

if TYPE_CHECKING:
    from config import AppConfig


class SessionAuth:
    """
    Gestión de sesiones en memoria con TTL.

    NOTA: en memoria = single-instance. Para producción multi-instancia,
    usar Redis como backend (pendiente Phase 2).
    """

    def __init__(self, cfg: "AppConfig") -> None:
        self._expire_hours = cfg.session_expire_hours
        self._users_hashed: dict[str, bytes] = self._hashear_usuarios(cfg.parsed_users())
        self._sesiones: dict[str, dict] = {}
        logger.info(
            "SessionAuth inicializado | usuarios={} | ttl={}h",
            len(self._users_hashed),
            self._expire_hours,
        )

    # ── Autenticación ────────────────────────────────────────────────────────

    @staticmethod
    def _hashear_usuarios(usuarios: dict[str, str]) -> dict[str, bytes]:
        """
        Hashea las contraseñas plaintext en bcrypt al arrancar.
        Las contraseñas originales no se almacenan.
        """
        hashed: dict[str, bytes] = {}
        for username, password in usuarios.items():
            hashed[username] = bcrypt.hashpw(
                password.encode("utf-8"),
                bcrypt.gensalt(rounds=12),
            )
        return hashed

    def verificar_credenciales(self, username: str, password: str) -> bool:
        """
        Verifica usuario+contraseña con bcrypt.checkpw (timing-safe).
        No loguea la contraseña en ningún caso.
        """
        hashed = self._users_hashed.get(username)
        if not hashed:
            # Usuario no existe — bcrypt dummy para prevenir timing attacks
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            return False
        return bcrypt.checkpw(password.encode("utf-8"), hashed)

    def primer_usuario(self) -> str:
        """Devuelve el primer usuario (admin por convención)."""
        return next(iter(self._users_hashed), "admin")

    def existe_usuario(self, username: str) -> bool:
        return username in self._users_hashed

    # ── Sesiones ─────────────────────────────────────────────────────────────

    def crear_sesion(self, username: str) -> str:
        """Crea una sesión y devuelve el token."""
        token = secrets.token_urlsafe(32)
        ahora = datetime.now(timezone.utc)
        self._sesiones[token] = {
            "username": username,
            "creado_en": ahora.isoformat(),
            "expira_en": (ahora + timedelta(hours=self._expire_hours)).isoformat(),
        }
        logger.debug("Sesión creada | usuario={}", username)
        return token

    def verificar_sesion(self, token: str) -> str | None:
        """
        Devuelve el username si la sesión es válida y no expiró.
        Elimina automáticamente sesiones expiradas al verificar.
        """
        sesion = self._sesiones.get(token)
        if not sesion:
            return None

        expira = datetime.fromisoformat(sesion["expira_en"])
        if datetime.now(timezone.utc) > expira:
            del self._sesiones[token]
            logger.debug("Sesión expirada y eliminada")
            return None

        return sesion["username"]

    def cerrar_sesion(self, token: str) -> None:
        self._sesiones.pop(token, None)

    def limpiar_expiradas(self) -> int:
        """
        Elimina sesiones expiradas. Llamar periódicamente.
        Devuelve el número de sesiones eliminadas.
        """
        ahora = datetime.now(timezone.utc)
        expiradas = [
            token
            for token, sesion in self._sesiones.items()
            if datetime.fromisoformat(sesion["expira_en"]) < ahora
        ]
        for token in expiradas:
            del self._sesiones[token]

        if expiradas:
            logger.debug("Sesiones expiradas eliminadas | count={}", len(expiradas))
        return len(expiradas)

    def sesiones_activas(self) -> int:
        return len(self._sesiones)
