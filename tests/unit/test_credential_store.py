"""
tests/unit/test_credential_store.py
-------------------------------------
Tests unitarios para app/agents/tools/credential_store.py.
"""

from __future__ import annotations

import pytest


CREDS_VALIDAS = {
    "user": "admin",
    "password": "secreto123",
    "auth_type": "password",
    "port": 22,
}

CREDS_SSH_KEY = {
    "user": "deploy",
    "ssh_key_path": "/home/deploy/.ssh/id_rsa",
    "auth_type": "ssh_key",
    "port": 2222,
}


class TestGetSet:
    def test_set_y_get(self, credential_store):
        credential_store.set("server-01", CREDS_VALIDAS)
        result = credential_store.get("server-01")
        assert result["user"] == "admin"
        assert result["password"] == "secreto123"

    def test_get_host_inexistente_devuelve_none(self, credential_store):
        assert credential_store.get("no-existe") is None

    def test_set_sobreescribe(self, credential_store):
        credential_store.set("server-01", CREDS_VALIDAS)
        nuevas = dict(CREDS_VALIDAS, password="nueva_pass")
        credential_store.set("server-01", nuevas)
        assert credential_store.get("server-01")["password"] == "nueva_pass"

    def test_set_ssh_key(self, credential_store):
        credential_store.set("server-02", CREDS_SSH_KEY)
        result = credential_store.get("server-02")
        assert result["auth_type"] == "ssh_key"
        assert result["ssh_key_path"] == "/home/deploy/.ssh/id_rsa"

    def test_port_por_defecto(self, credential_store):
        creds = {"user": "admin", "password": "pass"}
        credential_store.set("server-03", creds)
        assert credential_store.get("server-03")["port"] == 22

    def test_auth_type_inferido_de_ssh_key_path(self, credential_store):
        creds = {"user": "deploy", "ssh_key_path": "/key"}
        credential_store.set("server-04", creds)
        assert credential_store.get("server-04")["auth_type"] == "ssh_key"

    def test_auth_type_inferido_password(self, credential_store):
        creds = {"user": "admin", "password": "pass"}
        credential_store.set("server-05", creds)
        assert credential_store.get("server-05")["auth_type"] == "password"


class TestDelete:
    def test_delete_existente(self, credential_store):
        credential_store.set("server-del", CREDS_VALIDAS)
        result = credential_store.delete("server-del")
        assert result is True
        assert credential_store.get("server-del") is None

    def test_delete_inexistente_devuelve_false(self, credential_store):
        result = credential_store.delete("no-existe")
        assert result is False


class TestListHosts:
    def test_list_hosts(self, credential_store):
        credential_store.set("host-a", CREDS_VALIDAS)
        credential_store.set("host-b", CREDS_VALIDAS)
        hosts = credential_store.list_hosts()
        assert "host-a" in hosts
        assert "host-b" in hosts


class TestValidacion:
    def test_hostname_vacio_falla(self, credential_store):
        with pytest.raises(ValueError, match="hostname"):
            credential_store.set("", CREDS_VALIDAS)

    def test_hostname_espacios_falla(self, credential_store):
        with pytest.raises(ValueError, match="hostname"):
            credential_store.set("   ", CREDS_VALIDAS)

    def test_sin_user_falla(self, credential_store):
        with pytest.raises(ValueError, match="user"):
            credential_store.set("server-x", {"password": "pass"})

    def test_auth_type_invalido_falla(self, credential_store):
        with pytest.raises(ValueError, match="auth_type"):
            credential_store.set("server-x", {
                "user": "admin",
                "auth_type": "invalid_type",
            })

    def test_ssh_key_sin_path_falla(self, credential_store):
        with pytest.raises(ValueError, match="ssh_key_path"):
            credential_store.set("server-x", {
                "user": "admin",
                "auth_type": "ssh_key",
                # Sin ssh_key_path
            })

    def test_puerto_fuera_de_rango_falla(self, credential_store):
        with pytest.raises(ValueError, match="Puerto"):
            credential_store.set("server-x", {
                "user": "admin",
                "password": "pass",
                "port": 99999,
            })

    def test_puerto_cero_falla(self, credential_store):
        with pytest.raises(ValueError, match="Puerto"):
            credential_store.set("server-x", {"user": "admin", "port": 0})


class TestPersistencia:
    def test_datos_persisten_tras_recargar(self, tmp_path, test_config):
        """
        Verifica que el cifrado y la escritura atómica funcionan end-to-end:
        - store1 guarda credenciales cifradas en disco
        - store2 (nueva instancia, mismo fichero) las carga automáticamente en __init__
        """
        from unittest.mock import patch
        from agents.tools.credential_store import CredentialStore

        store_file = tmp_path / "persist_test.enc"

        # Ambas instancias creadas con la misma ruta de fichero parcheada.
        # CredentialStore.__init__ llama a _cargar() — store2 lee lo que store1 guardó.
        with patch("agents.tools.credential_store.cfg", test_config), \
             patch.object(test_config, "credential_store_path", str(store_file)):

            store1 = CredentialStore()
            store1.set("server-persist", CREDS_VALIDAS)

            # Segunda instancia: __init__ carga del mismo fichero, sin acceso privado
            store2 = CredentialStore()

        result = store2.get("server-persist")
        assert result is not None
        assert result["user"] == "admin"
        assert result["password"] == "secreto123"

    def test_clave_incorrecta_arranca_vacio(self, tmp_path, test_config):
        """
        Si el fichero fue cifrado con una clave diferente, la segunda instancia
        debe arrancar vacía en lugar de lanzar una excepción.
        """
        from unittest.mock import patch
        from agents.tools.credential_store import CredentialStore
        from config import AppConfig

        store_file = tmp_path / "alien_key.enc"

        # Escribir con clave A
        config_a = AppConfig(
            secret_key=test_config.secret_key,
            app_users=test_config.app_users,
            credential_store_key="clave-A-diferente-32chars-minimum!",
            llm_api_base_url=test_config.llm_api_base_url,
            redis_host=test_config.redis_host,
            mongo_uri=None,
        )
        with patch("agents.tools.credential_store.cfg", config_a), \
             patch.object(config_a, "credential_store_path", str(store_file)):
            store_a = CredentialStore()
            store_a.set("server-x", CREDS_VALIDAS)

        # Leer con clave distinta — debe arrancar vacío, no lanzar
        config_b = AppConfig(
            secret_key=test_config.secret_key,
            app_users=test_config.app_users,
            credential_store_key="clave-B-distinta-32chars-minimum!!",
            llm_api_base_url=test_config.llm_api_base_url,
            redis_host=test_config.redis_host,
            mongo_uri=None,
        )
        with patch("agents.tools.credential_store.cfg", config_b), \
             patch.object(config_b, "credential_store_path", str(store_file)):
            store_b = CredentialStore()

        assert store_b.get("server-x") is None  # Vacío, no crash
