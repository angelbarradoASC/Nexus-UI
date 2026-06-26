"""
app/nexus/access/service.py
-----------------------------
AgentAccessService — punto de entrada único para que los agentes
obtengan conexiones a dispositivos gestionados.

Flujo:
  1. El agente pide get_connection("dev-abc123")
  2. Se busca el dispositivo en CMDB → tipo + protocolo + IP
  3. Se obtiene la credencial del Vault (descifrado en memoria)
  4. Se instancia el conector adecuado según management_protocol
  5. Se devuelve un IConnection listo para usar

El agente no sabe si se conecta por SSH, WinRM o REST API.
"""

from __future__ import annotations

from loguru import logger

from nexus.cmdb.models import Device
from nexus.cmdb.source import CMDBSource
from nexus.connectors.base import IConnection
from nexus.connectors.ssh import SSHConnector
from nexus.vault.service import VaultService


class AgentAccessService:
    """
    Resuelve conexiones a dispositivos combinando CMDB + Vault.

    Inyectable en cualquier agente o ruta de API.
    """

    def __init__(self, cmdb: CMDBSource, vault: VaultService) -> None:
        self._cmdb  = cmdb
        self._vault = vault

    async def get_connection(self, device_id: str) -> IConnection:
        """
        Devuelve una conexión abierta al dispositivo.
        El caller es responsable de cerrarla (usar async with).

        Raises:
            KeyError:       si el dispositivo no existe en CMDB
            PermissionError: si el vault está bloqueado
            ValueError:     si el protocolo no está soportado
            RuntimeError:   si no hay credenciales configuradas
        """
        device = await self._cmdb.get_device(device_id)
        if device is None:
            raise KeyError(f"Dispositivo no encontrado en CMDB: {device_id}")

        if not device.enabled:
            raise ValueError(f"Dispositivo deshabilitado: {device_id}")

        credential = await self._vault.get_credential(device_id)
        if credential is None:
            raise RuntimeError(
                f"No hay credenciales configuradas para {device.name} ({device_id}). "
                "Añádelas en el Vault."
            )

        logger.info(
            "AccessService | device={} | ip={} | protocol={}",
            device.name, device.ip, device.management_protocol,
        )

        return await self._build_connection(device, credential)

    async def _build_connection(self, device: Device, credential) -> IConnection:
        protocol = device.management_protocol.lower()

        if protocol == "ssh":
            return await SSHConnector.from_credential(
                host=device.ip,
                port=device.port or 22,
                credential=credential,
            )

        # Futuros conectores — el patrón ya está aquí
        # if protocol == "winrm":
        #     return await WinRMConnector.from_credential(...)
        # if protocol == "rest_api":
        #     return await RestAPIConnector.from_credential(...)

        raise ValueError(
            f"Protocolo no soportado todavía: {protocol}. "
            "Soportados: ssh"
        )

    async def test_connection(self, device_id: str) -> dict[str, object]:
        """Test de conectividad para la UI del vault. No propaga excepciones."""
        try:
            async with await self.get_connection(device_id) as conn:
                result = await conn.run("echo nexus-ok", timeout=5)
            return {
                "ok":      result.ok,
                "output":  result.output,
                "message": "Conexión exitosa",
            }
        except Exception as exc:
            logger.warning("Test de conexión fallido | device={} | {}", device_id, exc)
            return {
                "ok":      False,
                "output":  "",
                "message": str(exc),
            }
