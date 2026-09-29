"""scripts/export_outreach_smtp_credentials.py
------------------------------------------------
Extrae UNA VEZ (o cada vez que cambie una contraseña) las credenciales SMTP
reales de las cuentas de Thunderbird usadas por Outreach — automato.es para
la via pyme, sls.assetsconsultores.es para la via IA/OT — y las guarda
cifradas en data/credentials.enc via CredentialStore.

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

# outreach_account (usado en daily_config.json / OutreachManager) -> cuenta real
ACCOUNTS: dict[str, str] = {
    "automato": "angel@automato.es",
    "sls_assetsconsultores": "vicentearaizeta@sls.assetsconsultores.es",
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
    for account_key, email in ACCOUNTS.items():
        try:
            creds = mail.resolve_outgoing_credentials(email)
        except Exception as exc:
            print(f"[FALLO] {email}: {exc}")
            continue
        if creds is None:
            print(f"[FALLO] No se encontró configuración SMTP para {email} en este perfil de Thunderbird.")
            continue

        store.set(
            f"outreach_smtp:{account_key}",
            {
                "user": creds["username"],
                "password": creds["password"],
                "port": creds["port"],
                "host": creds["host"],
                "email": creds["email"],
                "auth_type": "password",
            },
        )
        resolved += 1
        print(f"[OK] {email} -> outreach_smtp:{account_key} ({creds['host']}:{creds['port']})")

    print(f"\n{resolved}/{len(ACCOUNTS)} cuentas guardadas cifradas en {cfg.credential_store_path}")
    if resolved:
        print("Copia ese fichero al servidor junto al resto de ./data. No lo subas a git.")
    return 0 if resolved == len(ACCOUNTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
