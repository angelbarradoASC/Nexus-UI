"""
tests/unit/test_host_resolver.py
----------------------------------
Tests para HostResolver — known_hosts.json → DNS fallback.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── known_hosts.json de prueba ────────────────────────────────────────────────

_KNOWN_HOSTS_DATA = {
    "hosts": {
        "web01": {
            "ip":          "10.0.0.1",
            "type":        "linux",
            "port":        22,
            "user":        "admin",
            "description": "Servidor web principal",
            "enabled":     True,
        },
        "db01": {
            "ip":          "10.0.0.2",
            "type":        "linux",
            "port":        2222,
            "user":        "dbadmin",
            "description": "Base de datos",
            "enabled":     True,
        },
        "deshabilitado": {
            "ip":          "10.0.0.99",
            "type":        "linux",
            "port":        22,
            "user":        "admin",
            "description": "Host deshabilitado",
            "enabled":     False,
        },
    }
}


@pytest.fixture
def resolver(tmp_path):
    """HostResolver apuntando a un known_hosts.json temporal."""
    hosts_file = tmp_path / "known_hosts.json"
    hosts_file.write_text(json.dumps(_KNOWN_HOSTS_DATA), encoding="utf-8")

    with patch("agents.tools.host_resolver.HostResolver.__init__") as mock_init:
        def _init(self):
            self.hosts_file = hosts_file
            self.known_hosts = self._cargar_hosts()
            self.default_user = "defaultuser"
            self.default_port = 22
        mock_init.side_effect = _init
        from agents.tools.host_resolver import HostResolver
        r = HostResolver()
    return r


@pytest.fixture
def resolver_vacio(tmp_path):
    """HostResolver con fichero known_hosts vacío."""
    hosts_file = tmp_path / "known_hosts_empty.json"
    hosts_file.write_text(json.dumps({"hosts": {}}), encoding="utf-8")

    with patch("agents.tools.host_resolver.HostResolver.__init__") as mock_init:
        def _init(self):
            self.hosts_file = hosts_file
            self.known_hosts = self._cargar_hosts()
            self.default_user = "defaultuser"
            self.default_port = 22
        mock_init.side_effect = _init
        from agents.tools.host_resolver import HostResolver
        r = HostResolver()
    return r


# ═══════════════════════════════════════════════════════════════════════════════
# Resolución desde known_hosts.json
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolverDesdeKnownHosts:

    def test_host_conocido_devuelve_info(self, resolver):
        info = resolver.resolver("web01")
        assert info is not None
        assert info["ip"] == "10.0.0.1"

    def test_host_conocido_devuelve_todos_los_campos(self, resolver):
        info = resolver.resolver("web01")
        expected_fields = {"hostname", "ip", "tipo", "puerto", "usuario", "descripcion", "origen"}
        assert expected_fields.issubset(info.keys())

    def test_host_conocido_origen_es_known_hosts(self, resolver):
        info = resolver.resolver("web01")
        assert info["origen"] == "known_hosts"

    def test_puerto_personalizado_se_respeta(self, resolver):
        info = resolver.resolver("db01")
        assert info["puerto"] == 2222

    def test_usuario_personalizado_se_respeta(self, resolver):
        info = resolver.resolver("db01")
        assert info["usuario"] == "dbadmin"

    def test_host_deshabilitado_devuelve_none(self, resolver):
        info = resolver.resolver("deshabilitado")
        assert info is None

    def test_host_desconocido_no_en_json_fallback_dns(self, resolver):
        """Host no en known_hosts.json → intenta DNS."""
        with patch.object(resolver, "_resolver_dns", return_value={"hostname": "x"}) as mock_dns:
            resolver.resolver("hostdesconocido")
            mock_dns.assert_called_once_with("hostdesconocido")


# ═══════════════════════════════════════════════════════════════════════════════
# DNS fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestDNSFallback:

    def test_hostname_resuelto_por_dns(self, resolver):
        with patch("socket.gethostbyname", return_value="192.168.1.1"):
            info = resolver._resolver_dns("maquina.local")
        assert info is not None
        assert info["ip"] == "192.168.1.1"
        assert info["origen"] == "dns"

    def test_dns_devuelve_todos_los_campos(self, resolver):
        with patch("socket.gethostbyname", return_value="1.2.3.4"):
            info = resolver._resolver_dns("server.local")
        expected_fields = {"hostname", "ip", "tipo", "puerto", "usuario", "descripcion", "origen"}
        assert expected_fields.issubset(info.keys())

    def test_dns_usa_default_user(self, resolver):
        with patch("socket.gethostbyname", return_value="1.2.3.4"):
            info = resolver._resolver_dns("server.local")
        assert info["usuario"] == "defaultuser"

    def test_dns_usa_default_port(self, resolver):
        with patch("socket.gethostbyname", return_value="1.2.3.4"):
            info = resolver._resolver_dns("server.local")
        assert info["puerto"] == 22

    def test_dns_fallo_devuelve_none(self, resolver):
        with patch("socket.gethostbyname", side_effect=socket.gaierror("not found")):
            info = resolver._resolver_dns("noexiste.invalid")
        assert info is None

    def test_ip_directa_no_hace_dns_lookup(self, resolver):
        """Una IP no debe pasar por socket.gethostbyname."""
        with patch("socket.gethostbyname") as mock_dns:
            info = resolver._resolver_dns("10.1.2.3")
        mock_dns.assert_not_called()
        assert info is not None
        assert info["ip"] == "10.1.2.3"


# ═══════════════════════════════════════════════════════════════════════════════
# _es_ip
# ═══════════════════════════════════════════════════════════════════════════════

class TestEsIp:

    @pytest.mark.parametrize("texto,esperado", [
        ("192.168.1.1",   True),
        ("10.0.0.1",      True),
        ("255.255.255.0", True),
        ("0.0.0.0",       True),
        ("web01",         False),
        ("server.local",  False),
        ("",              False),
        ("999.999.999.999", False),  # IP inválida
        ("not.an.ip",     False),
    ])
    def test_es_ip(self, resolver, texto, esperado):
        assert resolver._es_ip(texto) == esperado


# ═══════════════════════════════════════════════════════════════════════════════
# listar_hosts_conocidos
# ═══════════════════════════════════════════════════════════════════════════════

class TestListarHostsConocidos:

    def test_devuelve_todos_los_hosts_del_json(self, resolver):
        hosts = resolver.listar_hosts_conocidos()
        assert "web01" in hosts
        assert "db01" in hosts
        assert "deshabilitado" in hosts

    def test_cada_host_tiene_campos_minimos(self, resolver):
        hosts = resolver.listar_hosts_conocidos()
        for nombre, info in hosts.items():
            assert "ip" in info
            assert "tipo" in info
            assert "habilitado" in info

    def test_campo_habilitado_correcto(self, resolver):
        hosts = resolver.listar_hosts_conocidos()
        assert hosts["web01"]["habilitado"] is True
        assert hosts["deshabilitado"]["habilitado"] is False

    def test_sin_hosts_devuelve_dict_vacio(self, resolver_vacio):
        hosts = resolver_vacio.listar_hosts_conocidos()
        assert hosts == {}


# ═══════════════════════════════════════════════════════════════════════════════
# recargar_hosts
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecargarHosts:

    def test_recarga_detecta_nuevos_hosts(self, tmp_path):
        """Si se añaden hosts al fichero, reload() los recoge."""
        hosts_file = tmp_path / "known_hosts.json"
        hosts_file.write_text(json.dumps({"hosts": {}}), encoding="utf-8")

        with patch("agents.tools.host_resolver.HostResolver.__init__") as mock_init:
            def _init(self):
                self.hosts_file = hosts_file
                self.known_hosts = self._cargar_hosts()
                self.default_user = "defaultuser"
                self.default_port = 22
            mock_init.side_effect = _init
            from agents.tools.host_resolver import HostResolver
            resolver = HostResolver()

        assert resolver.resolver("nuevo") is None  # No existe todavía

        # Escribir un nuevo host
        hosts_file.write_text(json.dumps({
            "hosts": {
                "nuevo": {"ip": "192.168.1.1", "type": "linux", "enabled": True}
            }
        }), encoding="utf-8")

        resolver.recargar_hosts()
        info = resolver.resolver("nuevo")
        assert info is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Carga con fichero malformado / inexistente
# ═══════════════════════════════════════════════════════════════════════════════

class TestCargaFicheroProblemas:

    def test_fichero_inexistente_arranca_vacio(self, tmp_path):
        non_existent = tmp_path / "no_existe.json"
        with patch("agents.tools.host_resolver.HostResolver.__init__") as mock_init:
            def _init(self):
                self.hosts_file = non_existent
                self.known_hosts = self._cargar_hosts()
                self.default_user = "u"
                self.default_port = 22
            mock_init.side_effect = _init
            from agents.tools.host_resolver import HostResolver
            resolver = HostResolver()
        assert resolver.known_hosts == {}

    def test_json_malformado_arranca_vacio(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")
        with patch("agents.tools.host_resolver.HostResolver.__init__") as mock_init:
            def _init(self):
                self.hosts_file = bad_file
                self.known_hosts = self._cargar_hosts()
                self.default_user = "u"
                self.default_port = 22
            mock_init.side_effect = _init
            from agents.tools.host_resolver import HostResolver
            resolver = HostResolver()
        assert resolver.known_hosts == {}
