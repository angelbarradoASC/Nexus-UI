"""
app/agents/ssh_agent.py
------------------------
Agente SSH — diagnóstico real de servidores Linux/Windows via Paramiko.

Cambios respecto a versión anterior:
  - Sustituye AutoAddPolicy() por RejectPolicy + known_hosts explícito
  - Fichero known_hosts cargable desde .env (SSH_KNOWN_HOSTS_FILE)
  - Clasificación de errores SSH más granular
  - No loguea contraseñas ni claves privadas en ningún nivel
  - asyncio.to_thread() para no bloquear el event loop
  - Usa BaseAgent + AgentResult
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import paramiko
from loguru import logger
from pydantic import BaseModel

from .base_agent import AgentResult, BaseAgent
from .generation_agent import GenerationAgent
from .tools.credential_store import CredentialStore
from .tools.host_resolver import HostResolver
from config import cfg


# ── Comandos de diagnóstico ───────────────────────────────────────────────────

_DIAGNOSTIC_COMMANDS: list[tuple[str, str]] = [
    ("uptime",                                                "Uptime y carga"),
    ("free -m",                                              "Memoria (MB)"),
    ("df -h",                                                "Disco"),
    ("ps aux --sort=-%cpu | head -10",                       "Top 10 procesos por CPU"),
    (
        "journalctl -n 50 --no-pager 2>/dev/null "
        "|| tail -n 50 /var/log/syslog 2>/dev/null",
        "Últimas 50 líneas de log",
    ),
]

# Path al fichero known_hosts (configurable via env)
_KNOWN_HOSTS_FILE: str = os.getenv(
    "SSH_KNOWN_HOSTS_FILE",
    str(Path.home() / ".ssh" / "known_hosts"),
)


# ── Modelo intermedio ─────────────────────────────────────────────────────────

class _CmdResult(BaseModel):
    label: str
    salida: str
    error: str = ""


# ── Agente ────────────────────────────────────────────────────────────────────

class SSHAgent(BaseAgent):
    """
    Diagnóstico SSH real con Paramiko.
    La conexión SSH corre en asyncio.to_thread() para no bloquear.
    """

    def __init__(self, router: Any) -> None:
        super().__init__(router)
        self._resolver = HostResolver()
        self._store    = CredentialStore()
        self._llm      = GenerationAgent(router)

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        hostname = entidades.get("servidor")
        if not hostname:
            prompt = (
                f"El usuario quiere diagnosticar un servidor pero no especificó cuál. "
                f"Su mensaje: '{consulta}'. Pregúntale el nombre o IP."
            )
            respuesta = await self._llm.generate_response(
                prompt, "system", self._construir_historial_ventana(historial)
            )
            return AgentResult(
                respuesta=respuesta, exito=True, agente=self._nombre()
            )

        # Resolver host
        host_info = self._resolver.resolver(hostname)
        if not host_info:
            return self._resultado_fallo(
                f"No se pudo resolver '{hostname}'. "
                f"Verifica que esté en known_hosts.json o que sea un hostname/IP válido.",
                "host_not_resolved",
            )

        # Obtener credenciales (sin logear valores)
        creds = (
            self._store.get(hostname)
            or self._store.get(host_info.get("ip", ""))
        )
        if not creds:
            return self._resultado_fallo(
                f"No hay credenciales para '{hostname}'. "
                f"Añádelas con el CredentialStore antes de conectar.",
                "no_credentials",
            )

        # Diagnóstico SSH en hilo separado
        try:
            raw_output = await asyncio.to_thread(
                self._ejecutar_diagnostico,
                host_info=host_info,
                creds=creds,
            )
        except _SSHAuthError as e:
            logger.warning("SSHAgent auth fallida | host={}", hostname)
            return self._resultado_fallo(
                f"Autenticación fallida en '{hostname}'. "
                f"Verifica usuario y contraseña/clave.",
                str(e),
            )
        except _SSHHostKeyError as e:
            logger.warning("SSHAgent host key desconocida | host={}", hostname)
            return self._resultado_fallo(
                f"La clave del servidor '{hostname}' no está en known_hosts. "
                f"Añade el servidor a tu fichero known_hosts antes de conectar.",
                str(e),
            )
        except _SSHConnectError as e:
            logger.warning("SSHAgent conexión fallida | host={}", hostname)
            return self._resultado_fallo(
                f"No se pudo conectar a '{hostname}': {e}",
                str(e),
            )
        except Exception as e:
            logger.exception("SSHAgent error inesperado | host={}", hostname)
            return self._resultado_fallo(
                f"Error inesperado al conectar con '{hostname}'.",
                str(e),
            )

        # Análisis LLM del output
        prompt = (
            f"Eres un experto en administración de sistemas Linux. "
            f"El usuario preguntó: '{consulta}'\n\n"
            f"Analiza el output de diagnóstico del servidor '{hostname}' "
            f"y responde de forma clara y concisa. "
            f"Si hay problemas, indícalos y sugiere acciones correctivas.\n\n"
            f"--- OUTPUT ---\n{raw_output}\n--- FIN ---"
        )
        respuesta = await self._llm.generate_response(
            prompt, "system", self._construir_historial_ventana(historial)
        )

        self.logger.info("SSHAgent diagnóstico completado | host={}", hostname)
        return AgentResult(
            respuesta=respuesta,
            exito=True,
            agente=self._nombre(),
            datos={"hostname": hostname, "host_info": host_info},
        )

    # ── Lógica SSH (síncrona — en to_thread) ──────────────────────────────────

    def _ejecutar_diagnostico(
        self,
        host_info: dict[str, Any],
        creds: dict[str, Any],
    ) -> str:
        """
        Conecta por SSH y ejecuta los comandos de diagnóstico.
        Se ejecuta en un hilo daemon via asyncio.to_thread().
        No loguea contraseñas ni rutas de claves.
        """
        client = paramiko.SSHClient()

        # ── Política de host keys ─────────────────────────────────────────
        # RejectPolicy por defecto: rechaza hosts desconocidos.
        # Si existe el fichero known_hosts, lo carga para verificar.
        known_hosts = Path(_KNOWN_HOSTS_FILE)
        if known_hosts.exists():
            client.load_host_keys(str(known_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            logger.debug("SSHAgent | known_hosts cargado | {}", known_hosts)
        else:
            # En entorno sin known_hosts (CI, contenedor): WarningPolicy
            # loguea la clave pero no rechaza. Anotar como deuda técnica.
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
            logger.warning(
                "SSHAgent | known_hosts no encontrado en {} — usando WarningPolicy. "
                "Configura SSH_KNOWN_HOSTS_FILE en producción.",
                known_hosts,
            )

        connect_kwargs: dict[str, Any] = {
            "hostname": host_info["ip"],
            "port":     host_info.get("puerto", creds.get("port", 22)),
            "username": creds["user"],
            "timeout":  cfg.ssh_timeout,
            "look_for_keys": False,
            "allow_agent":   False,
        }

        auth_type = creds.get("auth_type", "password")
        if auth_type == "ssh_key" and creds.get("ssh_key_path"):
            connect_kwargs["key_filename"] = creds["ssh_key_path"]
        else:
            connect_kwargs["password"] = creds.get("password", "")

        try:
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException as e:
            raise _SSHAuthError(str(e)) from e
        except paramiko.BadHostKeyException as e:
            raise _SSHHostKeyError(str(e)) from e
        except (paramiko.SSHException, OSError) as e:
            raise _SSHConnectError(str(e)) from e

        resultados: list[str] = []
        try:
            for cmd, label in _DIAGNOSTIC_COMMANDS:
                try:
                    _, stdout, stderr = client.exec_command(cmd, timeout=30)
                    out = stdout.read().decode(errors="replace").strip()
                    err = stderr.read().decode(errors="replace").strip()
                    if out:
                        resultados.append(f"### {label}\n```\n{out}\n```")
                    elif err:
                        resultados.append(f"### {label}\n```\n[stderr] {err}\n```")
                except Exception as e:
                    resultados.append(f"### {label}\n[error: {type(e).__name__}]")
        finally:
            client.close()

        return "\n\n".join(resultados) if resultados else "Sin output de los comandos."


# ── Excepciones internas ──────────────────────────────────────────────────────

class _SSHAuthError(Exception):
    """Fallo de autenticación SSH."""

class _SSHHostKeyError(Exception):
    """Clave de host SSH no reconocida."""

class _SSHConnectError(Exception):
    """Error de conexión SSH (red, timeout, puerto)."""
