"""
tests/unit/test_config.py
--------------------------
Tests unitarios para app/config.py.

Cubre:
  - Parsing de APP_USERS
  - Detección de keys inseguras en producción (fallo duro)
  - Tolerancia en debug mode (solo warning)
  - Properties calculadas (l0_url, is_desktop)
  - jira_configured()
"""

from __future__ import annotations

import pytest


def make_config(**kwargs):
    """Helper: crea AppConfig con overrides."""
    from config import AppConfig
    defaults = dict(
        debug=True,
        app_environment="development",
        secret_key="safe-secret-key-32-chars-minimum!",
        app_users="admin:adminpass",
        credential_store_key="safe-encryption-key-32chars-min!",
        mongo_uri=None,
    )
    defaults.update(kwargs)
    return AppConfig(**defaults)


# ── parsed_users ──────────────────────────────────────────────────────────────

class TestParsedUsers:
    def test_usuario_simple(self):
        cfg = make_config(app_users="admin:secret")
        assert cfg.parsed_users() == {"admin": "secret"}

    def test_multiples_usuarios(self):
        cfg = make_config(app_users="admin:pass1,user2:pass2")
        users = cfg.parsed_users()
        assert users == {"admin": "pass1", "user2": "pass2"}

    def test_ignora_entradas_sin_dos_puntos(self):
        cfg = make_config(app_users="admin:pass,invalid_entry")
        users = cfg.parsed_users()
        assert "admin" in users
        assert "invalid_entry" not in users

    def test_espacios_alrededor(self):
        cfg = make_config(app_users=" admin : secret ")
        assert cfg.parsed_users() == {"admin": "secret"}

    def test_password_con_dos_puntos(self):
        """Una contraseña puede contener ':' — solo se parte en el primero."""
        cfg = make_config(app_users="admin:pass:word")
        assert cfg.parsed_users() == {"admin": "pass:word"}


# ── Seguridad en producción ───────────────────────────────────────────────────

class TestSeguridadProduccion:
    def test_secret_key_insegura_en_produccion_falla(self):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            make_config(
                debug=False,
                app_environment="production",
                secret_key="change-this-secret-key",
            )

    def test_credential_store_key_insegura_en_produccion_falla(self):
        with pytest.raises(ValueError, match="CREDENTIAL_STORE_KEY"):
            make_config(
                debug=False,
                app_environment="production",
                credential_store_key="change-this-encryption-key-32chars",
            )

    def test_ambas_inseguras_en_produccion_falla_con_dos_mensajes(self):
        with pytest.raises(ValueError) as exc_info:
            make_config(
                debug=False,
                app_environment="production",
                secret_key="change-this-secret-key",
                credential_store_key="change-this-encryption-key-32chars",
            )
        mensaje = str(exc_info.value)
        assert "SECRET_KEY" in mensaje
        assert "CREDENTIAL_STORE_KEY" in mensaje

    def test_keys_inseguras_en_debug_no_falla(self):
        """En debug=True no debe fallar, solo advertir."""
        import warnings
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            cfg = make_config(
                debug=True,
                secret_key="change-this-secret-key",
                credential_store_key="change-this-encryption-key-32chars",
            )
        assert cfg.debug is True

    def test_keys_seguras_en_produccion_ok(self):
        cfg = make_config(
            debug=False,
            app_environment="production",
            secret_key="super-secure-production-key-32!",
            credential_store_key="super-secure-cred-key-32chars!!",
            mongo_uri="mongodb://secure-user:secure-pass@mongodb:27017/nexus_db?authSource=admin",
            redis_password="secure-redis-password",
            session_secure_cookie=True,
        )
        assert cfg.debug is False


# ── Properties calculadas ─────────────────────────────────────────────────────

class TestProperties:
    def test_is_desktop_false_por_defecto(self):
        cfg = make_config()
        assert cfg.is_desktop is False

    def test_is_desktop_true(self):
        cfg = make_config(nexus_context="desktop_app")
        assert cfg.is_desktop is True

    def test_l0_url_desde_llm_l0_url(self):
        cfg = make_config(llm_l0_url="http://localhost:1234/v1")
        assert cfg.l0_url == "http://localhost:1234/v1"

    def test_l0_url_fallback_a_legacy(self):
        cfg = make_config(
            llm_l0_url=None,
            llm_api_base_url="http://legacy:1234/v1",
        )
        assert cfg.l0_url == "http://legacy:1234/v1"

    def test_l0_url_prioridad_l0_sobre_legacy(self):
        cfg = make_config(
            llm_l0_url="http://nuevo:1234/v1",
            llm_api_base_url="http://legacy:1234/v1",
        )
        assert cfg.l0_url == "http://nuevo:1234/v1"

    def test_l0_url_none_si_no_configurado(self):
        cfg = make_config(llm_l0_url=None, llm_api_base_url=None)
        assert cfg.l0_url is None

    def test_l1_url_desde_llm_l1_url(self):
        cfg = make_config(llm_l1_url="https://groq.example/v1", llm_l1_key="abc")
        assert cfg.l1_url == "https://groq.example/v1"

    def test_l1_url_fallback_a_nvidia_si_habilitado(self):
        cfg = make_config(
            llm_l1_url=None,
            llm_l1_key=None,
            nvidia_use_as_l1=True,
            nvidia_api_key="nvapi-test",
        )
        assert cfg.l1_url == "https://integrate.api.nvidia.com/v1"

    def test_l1_key_fallback_a_nvidia(self):
        cfg = make_config(
            llm_l1_key=None,
            nvidia_use_as_l1=True,
            nvidia_api_key="nvapi-test",
        )
        assert cfg.l1_key == "nvapi-test"

    def test_l1_model_fallback_a_nvidia(self):
        cfg = make_config(
            llm_l1_url=None,
            llm_l1_key=None,
            nvidia_use_as_l1=True,
            nvidia_api_key="nvapi-test",
            nvidia_llm_model="meta/llama-3.1-8b-instruct",
        )
        assert cfg.l1_model == "meta/llama-3.1-8b-instruct"


# ── jira_configured ───────────────────────────────────────────────────────────

class TestJiraConfigured:
    def test_false_si_use_jira_false(self):
        cfg = make_config(use_jira=False)
        assert cfg.jira_configured() is False

    def test_false_si_falta_url(self):
        cfg = make_config(use_jira=True, jira_url="", jira_email="a@b.com", jira_api_token="tok")
        assert cfg.jira_configured() is False

    def test_true_si_todo_configurado(self):
        cfg = make_config(
            use_jira=True,
            jira_url="https://myjira.atlassian.net",
            jira_email="user@company.com",
            jira_api_token="api-token-123",
        )
        assert cfg.jira_configured() is True
