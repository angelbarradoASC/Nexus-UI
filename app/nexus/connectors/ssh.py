"""
app/nexus/connectors/ssh.py
-----------------------------
SSHConnector — conector SSH para Linux y equipos de red.

Usa paramiko internamente. El AgentExecutionContext recibe un IConnection
ya abierto — no necesita saber que hay SSH debajo.

Gestión de conexiones:
  - Se abre en connect() o __aenter__
  - Se cierra en close() o __aexit__
  - Timeout configurable por comando
  - stderr separado de stdout (el guardrail ve el comando, no el output)
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import paramiko
from loguru import logger

from nexus.connectors.base import CommandResult, IConnection

if TYPE_CHECKING:
    from nexus.vault.service import Credential


class SSHConnector(IConnection):
    """
    Conector SSH usando paramiko.

    Soporta:
      - Autenticación por password
      - Autenticación por SSH key (PEM en memoria — nunca escrita a disco)
      - Host key policy: AutoAddPolicy (aceptable en red interna controlada)
    """

    def __init__(
        self,
        host:    str,
        port:    int = 22,
        timeout: int = 10,
    ) -> None:
        self._host    = host
        self._port    = port
        self._timeout = timeout
        self._client: paramiko.SSHClient | None = None

    @classmethod
    async def from_credential(
        cls,
        host:       str,
        port:       int,
        credential: "Credential",
    ) -> "SSHConnector":
        """Crea y conecta el conector a partir de una credencial del vault."""
        conn = cls(host=host, port=port)
        await conn.connect(credential)
        return conn

    async def connect(self, credential: "Credential") -> None:
        """Abre la conexión SSH. Lanza excepción si falla."""
        def _connect():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs: dict = {
                "hostname": self._host,
                "port":     self._port,
                "username": credential.username,
                "timeout":  self._timeout,
                "look_for_keys": False,
                "allow_agent":   False,
            }

            if credential.auth_method == "ssh_key" and credential.ssh_key:
                pkey = paramiko.RSAKey.from_private_key(
                    io.StringIO(credential.ssh_key)
                )
                connect_kwargs["pkey"] = pkey
            else:
                connect_kwargs["password"] = credential.secret

            client.connect(**connect_kwargs)
            return client

        logger.debug("SSH conectando a {}:{}", self._host, self._port)
        self._client = await asyncio.to_thread(_connect)
        logger.info("SSH conectado | {}@{}:{}", credential.username, self._host, self._port)

    async def run(self, command: str, timeout: int = 30) -> CommandResult:
        """Ejecuta un comando y devuelve CommandResult."""
        if self._client is None:
            raise RuntimeError("SSHConnector no conectado. Llama a connect() primero.")

        def _exec():
            _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            return (
                stdout.read().decode("utf-8", errors="replace"),
                stderr.read().decode("utf-8", errors="replace"),
                exit_code,
            )

        logger.debug("SSH exec | {}:{} | {}", self._host, self._port, command[:80])
        out, err, code = await asyncio.to_thread(_exec)
        return CommandResult(stdout=out, stderr=err, exit_code=code)

    async def close(self) -> None:
        if self._client:
            await asyncio.to_thread(self._client.close)
            self._client = None
            logger.debug("SSH desconectado | {}:{}", self._host, self._port)
