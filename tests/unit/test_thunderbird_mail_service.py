"""tests/unit/test_thunderbird_mail_service.py

ThunderbirdMailManager.resolve_outgoing_credentials — resuelve host/puerto/
usuario/contraseña del servidor SMTP saliente de una cuenta real de
Thunderbird (no solo IMAP, que es lo unico que se leia antes). Usado por
scripts/export_outreach_smtp_credentials.py para dejar de depender de una
sola cuenta SMTP global en .env. Los tests usan un prefs.js/logins.json
fake — nunca tocan la NSS real de Thunderbird.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.mail.service import ThunderbirdCredentialStore, ThunderbirdMailManager

_PREFS_JS = """
user_pref("mail.accountmanager.accounts", "account1");
user_pref("mail.account.account1.server", "server1");
user_pref("mail.account.account1.identities", "id1");
user_pref("mail.server.server1.type", "imap");
user_pref("mail.server.server1.hostname", "imap.sls.assetsconsultores.es");
user_pref("mail.server.server1.port", 993);
user_pref("mail.server.server1.userName", "vicentearaizeta@sls.assetsconsultores.es");
user_pref("mail.identity.id1.useremail", "vicentearaizeta@sls.assetsconsultores.es");
user_pref("mail.identity.id1.fullName", "Vicente Araizeta");
user_pref("mail.identity.id1.smtpServer", "smtp1");
user_pref("mail.smtpserver.smtp1.hostname", "smtp.sls.assetsconsultores.es");
user_pref("mail.smtpserver.smtp1.port", 465);
user_pref("mail.smtpserver.smtp1.username", "vicentearaizeta@sls.assetsconsultores.es");
"""

_LOGINS_JSON = {
    "logins": [
        {
            "hostname": "smtp://smtp.sls.assetsconsultores.es",
            "encryptedUsername": "enc-user",
            "encryptedPassword": "enc-pass",
        },
        {
            "hostname": "imap://imap.sls.assetsconsultores.es",
            "encryptedUsername": "enc-imap-user",
            "encryptedPassword": "enc-imap-pass",
        }
    ]
}


@pytest.fixture
def profile_dir(tmp_path: Path) -> Path:
    profile = tmp_path / "Profiles" / "testprofile"
    profile.mkdir(parents=True)
    (profile / "prefs.js").write_text(_PREFS_JS, encoding="utf-8")
    (profile / "logins.json").write_text(json.dumps(_LOGINS_JSON), encoding="utf-8")
    return profile


@pytest.fixture
def cfg(tmp_path: Path, profile_dir: Path):
    return type(
        "MailCfg",
        (),
        {
            "thunderbird_enabled": True,
            "thunderbird_profile_root": str(tmp_path),
            "thunderbird_profile_name": "testprofile",
            "thunderbird_install_dir": "",
            "thunderbird_priority_accounts": "",
            "thunderbird_message_limit_per_account": 20,
            "thunderbird_priority_total_limit": 30,
        },
    )()


@pytest.fixture(autouse=True)
def _fake_nss_decrypt(monkeypatch):
    """decrypt_login real llama a nss3.dll via ctypes — no disponible (ni
    deseable) en tests. Se sustituye por un descifrado fake y determinista."""

    def _fake_decrypt(self, encrypted_username: str, encrypted_password: str) -> tuple[str, str]:
        return encrypted_username.replace("enc-", ""), encrypted_password.replace("enc-", "")

    monkeypatch.setattr(ThunderbirdCredentialStore, "decrypt_login", _fake_decrypt)


def test_resolve_outgoing_credentials_finds_real_smtp_server(cfg):
    manager = ThunderbirdMailManager(cfg=cfg)

    creds = manager.resolve_outgoing_credentials("vicentearaizeta@sls.assetsconsultores.es")

    assert creds is not None
    assert creds["host"] == "smtp.sls.assetsconsultores.es"
    assert creds["port"] == 465
    assert creds["username"] == "user"
    assert creds["password"] == "pass"


def test_resolve_outgoing_credentials_returns_none_for_unknown_email(cfg):
    manager = ThunderbirdMailManager(cfg=cfg)

    creds = manager.resolve_outgoing_credentials("nadie@dominio-inexistente.es")

    assert creds is None


def test_resolve_outgoing_credentials_returns_none_without_profile(cfg):
    cfg.thunderbird_profile_name = "perfil-que-no-existe"
    manager = ThunderbirdMailManager(cfg=cfg)

    creds = manager.resolve_outgoing_credentials("vicentearaizeta@sls.assetsconsultores.es")

    assert creds is None


def test_resolve_incoming_credentials_finds_real_imap_server(cfg):
    manager = ThunderbirdMailManager(cfg=cfg)

    creds = manager.resolve_incoming_credentials("vicentearaizeta@sls.assetsconsultores.es")

    assert creds is not None
    assert creds["host"] == "imap.sls.assetsconsultores.es"
    assert creds["port"] == 993
    assert creds["username"] == "imap-user"
    assert creds["password"] == "imap-pass"


def test_resolve_incoming_credentials_returns_none_for_unknown_email(cfg):
    manager = ThunderbirdMailManager(cfg=cfg)

    creds = manager.resolve_incoming_credentials("nadie@dominio-inexistente.es")

    assert creds is None
