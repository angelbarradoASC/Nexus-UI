from __future__ import annotations

import pytest


def make_secure_production_config(**overrides):
    from config import AppConfig

    defaults = dict(
        app_environment="production",
        debug=False,
        secret_key="safe-production-secret-key-32chars!!",
        credential_store_key="safe-production-store-key-32chars!!",
        app_users="ops:strong-password",
        mongo_uri="mongodb://secure-user:secure-pass@mongodb:27017/nexus_db?authSource=admin",
        redis_password="secure-redis-password",
        session_secure_cookie=True,
        brave_search_enabled=False,
        google_places_enabled=False,
        outreach_enabled=False,
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


def test_development_acepta_defaults_heredados():
    from config import AppConfig

    cfg = AppConfig(
        app_environment="development",
        secret_key="change-this-secret-key",
        credential_store_key="change-this-encryption-key-32chars",
        app_users="admin:changeme",
        session_secure_cookie=False,
        mongo_uri=None,
        redis_password=None,
    )

    assert cfg.app_environment == "development"


def test_production_falla_con_defaults_inseguros():
    with pytest.raises(ValueError) as exc_info:
        make_secure_production_config(
            secret_key="change-this-secret-key",
            credential_store_key="change-this-encryption-key-32chars",
            app_users="admin:changeme",
        )

    message = str(exc_info.value)
    assert "SECRET_KEY" in message
    assert "CREDENTIAL_STORE_KEY" in message
    assert "APP_USERS" in message


def test_production_falla_si_falta_redis_password():
    with pytest.raises(ValueError, match="REDIS_PASSWORD"):
        make_secure_production_config(redis_password=None)


def test_production_falla_si_session_secure_cookie_es_false():
    with pytest.raises(ValueError, match="SESSION_SECURE_COOKIE"):
        make_secure_production_config(session_secure_cookie=False)


def test_production_acepta_configuracion_minima_segura():
    cfg = make_secure_production_config()

    assert cfg.app_environment == "production"
    assert cfg.session_secure_cookie is True


def test_mensajes_de_error_no_exponen_valores_sensibles():
    secret = "super-secret-visible-value"
    with pytest.raises(ValueError) as exc_info:
        make_secure_production_config(secret_key="change-this-secret-key", redis_password=secret)

    message = str(exc_info.value)
    assert secret not in message
