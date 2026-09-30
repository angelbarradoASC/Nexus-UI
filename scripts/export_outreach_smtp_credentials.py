"""scripts/export_outreach_smtp_credentials.py
------------------------------------------------
Extrae UNA VEZ (o cada vez que cambie una contraseña) las credenciales SMTP
(envío) e IMAP (lectura de respuestas) reales de las 4 cuentas de
Thunderbird disponibles, y las guarda cifradas en data/credentials.enc via
CredentialStore.

Solo funciona en la maquina donde Thunderbird esta instalado (el perfil y
las credenciales NSS son locales). El fichero .enc resultante se copia
despues al servidor junto al resto de ./data — nunca a .env, nunca a git
(data/ ya esta en .gitignore).

Uso:
    python scripts/export_outreach_smtp_credentials.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "app"))

from agents.tools.credential_store import CredentialStore  # noqa: E402
from config import cfg  # noqa: E402
from nexus.mail import ThunderbirdMailManager  # noqa: E402

# outreach_account (elegible en la UI de Campaña / daily_config.json) ->
# cuenta real de Thunderbird. Las 4 cuentas configuradas hoy — se puede
# lanzar cualquier línea desde cualquiera de ellas.
ACCOUNTS: dict[str, str] = {
    "automato": "angel@automato.es",
    "sls_assetsconsultores": "vicentearaizeta@sls.assetsconsultores.es",
    "sls_mayte": "MayteRojas@sls.assetsconsultores.es",
    "assets_angel": "angel.barrado@assetsconsultores.es",
}


def main() -> int:
    if not cfg.thunderbird_enabled:
        print(
            "THUNDERBIRD_ENABLED=false en .env — actívalo antes de extraer "
            "(evita leer el perfil local de Thunderbird sin permiso explícito)."
        )
        return 1

    mail = ThunderbirdMailManager(cfg=cfg)
    store = CredentialStore()

    resolved = 0
    total = len(ACCOUNTS) * 2  # SMTP + IMAP por cuenta
    for account_key, email in ACCOUNTS.items():
        try:
            smtp_creds = mail.resolve_outgoing_credentials(email)
        except Exception as exc:
            print(f"[FALLO] SMTP {email}: {exc}")
            smtp_creds = None
        if smtp_creds is None:
            print(f"[FALLO] No se encontró configuración SMTP para {email} en este perfil de Thunderbird.")
        else:
            store.set(
                f"outreach_smtp:{account_key}",
                {
                    "user": smtp_creds["username"],
                    "password": smtp_creds["password"],
                    "port": smtp_creds["port"],
                    "host": smtp_creds["host"],
                    "email": smtp_creds["email"],
                    "auth_type": "password",
                },
            )
            resolved += 1
            print(f"[OK] SMTP {email} -> outreach_smtp:{account_key} ({smtp_creds['host']}:{smtp_creds['port']})")

        try:
            imap_creds = mail.resolve_incoming_credentials(email)
        except Exception as exc:
            print(f"[FALLO] IMAP {email}: {exc}")
            imap_creds = None
        if imap_creds is None:
            print(f"[FALLO] No se encontró configuración IMAP para {email} en este perfil de Thunderbird.")
        else:
            store.set(
                f"outreach_imap:{account_key}",
                {
                    "user": imap_creds["username"],
                    "password": imap_creds["password"],
                    "port": imap_creds["port"],
                    "host": imap_creds["host"],
                    "email": imap_creds["email"],
                    "auth_type": "password",
                },
            )
            resolved += 1
            print(f"[OK] IMAP {email} -> outreach_imap:{account_key} ({imap_creds['host']}:{imap_creds['port']})")

    print(f"\n{resolved}/{total} credenciales guardadas cifradas en {cfg.credential_store_path}")
    if resolved:
        print("Copia ese fichero al servidor junto al resto de ./data. No lo subas a git.")
    return 0 if resolved == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
