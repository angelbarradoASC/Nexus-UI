import os
import json
import socket
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class HostResolver:
    """
    Resuelve nombres de servidores a información de conexión.
    Prioridades: known_hosts.json → DNS fallback
    """

    def __init__(self):
        self.hosts_file = Path('/app/data/known_hosts.json')
        self.known_hosts = self._cargar_hosts()
        self.default_user = os.getenv('DEFAULT_SSH_USER', 'admin')
        self.default_port = int(os.getenv('DEFAULT_SSH_PORT', '22'))
        logger.info(f"HostResolver inicializado — {len(self.known_hosts)} hosts en cache local")

    def _cargar_hosts(self) -> Dict:
        try:
            if self.hosts_file.exists():
                with open(self.hosts_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    hosts = data.get('hosts', {})
                    logger.info(f"Cargados {len(hosts)} hosts desde {self.hosts_file}")
                    return hosts
            logger.warning(f"Fichero {self.hosts_file} no existe, cache local vacío")
            return {}
        except Exception as e:
            logger.error(f"Error cargando known_hosts.json: {e}")
            return {}

    def resolver(self, hostname: str) -> Optional[Dict]:
        """
        Resuelve un hostname a información de conexión.

        Retorna:
            {hostname, ip, tipo, puerto, usuario, descripcion, origen}
            o None si no se puede resolver.
        """
        logger.info(f"Resolviendo hostname: {hostname}")

        # Prioridad 1: known_hosts.json
        if hostname in self.known_hosts:
            host_data = self.known_hosts[hostname]
            if not host_data.get('enabled', True):
                logger.warning(f"Host {hostname} en known_hosts pero deshabilitado")
                return None
            logger.info(f"Host {hostname} resuelto desde known_hosts.json")
            return {
                'hostname': hostname,
                'ip': host_data.get('ip'),
                'tipo': host_data.get('type', 'linux'),
                'puerto': host_data.get('port', self.default_port),
                'usuario': host_data.get('user', self.default_user),
                'descripcion': host_data.get('description', ''),
                'origen': 'known_hosts',
            }

        # Prioridad 2: DNS fallback
        return self._resolver_dns(hostname)

    def _resolver_dns(self, hostname: str) -> Optional[Dict]:
        try:
            if self._es_ip(hostname):
                ip = hostname
            else:
                ip = socket.gethostbyname(hostname)
                logger.info(f"Hostname {hostname} resuelto por DNS a {ip}")

            return {
                'hostname': hostname,
                'ip': ip,
                'tipo': 'linux',
                'puerto': self.default_port,
                'usuario': self.default_user,
                'descripcion': 'Resuelto por DNS (sin metadata)',
                'origen': 'dns',
            }
        except socket.gaierror as e:
            logger.error(f"No se pudo resolver {hostname} por DNS: {e}")
            return None
        except Exception as e:
            logger.error(f"Error resolviendo {hostname}: {e}")
            return None

    def _es_ip(self, texto: str) -> bool:
        try:
            socket.inet_aton(texto)
            return True
        except socket.error:
            return False

    def listar_hosts_conocidos(self) -> Dict:
        return {
            nombre: {
                'ip': info.get('ip'),
                'tipo': info.get('type'),
                'descripcion': info.get('description', ''),
                'habilitado': info.get('enabled', True),
            }
            for nombre, info in self.known_hosts.items()
        }

    def recargar_hosts(self):
        logger.info("Recargando known_hosts.json...")
        self.known_hosts = self._cargar_hosts()
