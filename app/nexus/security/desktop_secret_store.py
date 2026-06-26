from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SecretBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class DesktopSecretStoreError(RuntimeError):
    """Controlled backend error that never includes secret values."""


@dataclass(slots=True)
class DesktopProviderSecretStore:
    backend: SecretBackend
    service_name: str = "nexus.desktop.provider"

    def load(self, credential_ref: str) -> str:
        ref = str(credential_ref or "").strip()
        if not ref:
            return ""
        try:
            value = self.backend.get_password(self.service_name, ref)
        except Exception as exc:  # pragma: no cover
            raise DesktopSecretStoreError(
                "No se pudo leer la credencial del almacen seguro del escritorio."
            ) from exc
        return str(value or "")

    def save(self, credential_ref: str, secret: str) -> None:
        ref = str(credential_ref or "").strip()
        if not ref:
            raise DesktopSecretStoreError("No se pudo guardar la credencial segura del escritorio.")
        try:
            self.backend.set_password(self.service_name, ref, secret)
        except Exception as exc:  # pragma: no cover
            raise DesktopSecretStoreError(
                "No se pudo guardar la credencial en el almacen seguro del escritorio."
            ) from exc

    def delete(self, credential_ref: str) -> None:
        ref = str(credential_ref or "").strip()
        if not ref:
            return
        try:
            self.backend.delete_password(self.service_name, ref)
        except Exception as exc:  # pragma: no cover
            raise DesktopSecretStoreError(
                "No se pudo eliminar la credencial del almacen seguro del escritorio."
            ) from exc


def build_desktop_provider_secret_store() -> DesktopProviderSecretStore:
    try:
        import keyring
    except Exception as exc:  # pragma: no cover
        raise DesktopSecretStoreError(
            "No hay un backend compatible de almacen seguro para el escritorio."
        ) from exc
    return DesktopProviderSecretStore(backend=keyring)
