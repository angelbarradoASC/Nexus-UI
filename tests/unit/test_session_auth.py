"""
tests/unit/test_session_auth.py
--------------------------------
Tests unitarios para app/utils/session_auth.py.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def auth(test_config):
    from utils.session_auth import SessionAuth
    return SessionAuth(test_config)


class TestVerificarCredenciales:
    def test_credenciales_correctas(self, auth):
        assert auth.verificar_credenciales("testuser", "testpass") is True

    def test_password_incorrecta(self, auth):
        assert auth.verificar_credenciales("testuser", "wrong") is False

    def test_usuario_inexistente(self, auth):
        assert auth.verificar_credenciales("noexiste", "cualquier") is False

    def test_usuario_vacio(self, auth):
        assert auth.verificar_credenciales("", "testpass") is False

    def test_password_vacia(self, auth):
        assert auth.verificar_credenciales("testuser", "") is False


class TestSesiones:
    def test_crear_sesion_devuelve_token(self, auth):
        token = auth.crear_sesion("testuser")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_verificar_sesion_valida(self, auth):
        token = auth.crear_sesion("testuser")
        username = auth.verificar_sesion(token)
        assert username == "testuser"

    def test_verificar_sesion_inexistente(self, auth):
        assert auth.verificar_sesion("token-falso-xxx") is None

    def test_cerrar_sesion(self, auth):
        token = auth.crear_sesion("testuser")
        auth.cerrar_sesion(token)
        assert auth.verificar_sesion(token) is None

    def test_cerrar_sesion_inexistente_no_falla(self, auth):
        auth.cerrar_sesion("token-que-no-existe")  # no debe lanzar

    def test_sesiones_activas_count(self, auth):
        t1 = auth.crear_sesion("testuser")
        t2 = auth.crear_sesion("testuser")
        assert auth.sesiones_activas() >= 2
        auth.cerrar_sesion(t1)
        auth.cerrar_sesion(t2)

    def test_tokens_son_unicos(self, auth):
        tokens = {auth.crear_sesion("testuser") for _ in range(10)}
        assert len(tokens) == 10  # sin colisiones

    def test_sesion_expirada_devuelve_none(self, auth):
        """Manipula la expiración para testear el TTL."""
        token = auth.crear_sesion("testuser")
        # Sobreescribir la expiración al pasado
        sesion = auth._sesiones[token]
        sesion["expira_en"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        assert auth.verificar_sesion(token) is None
        assert token not in auth._sesiones  # debe haberse limpiado

    def test_limpiar_expiradas(self, auth):
        token = auth.crear_sesion("testuser")
        # Expirar la sesión manualmente
        auth._sesiones[token]["expira_en"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        count = auth.limpiar_expiradas()
        assert count >= 1
        assert token not in auth._sesiones


class TestHelpers:
    def test_primer_usuario(self, auth):
        primer = auth.primer_usuario()
        assert primer in ("testuser", "admin")

    def test_existe_usuario_true(self, auth):
        assert auth.existe_usuario("testuser") is True

    def test_existe_usuario_false(self, auth):
        assert auth.existe_usuario("noexiste") is False
