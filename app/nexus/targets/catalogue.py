"""Canonical technology catalogue for multi-platform Nexus investigations."""

from __future__ import annotations

from nexus.targets.models import AccessProfile, TechnologyProfile


class TechnologyCatalogue:
    """Static catalogue of the first infrastructure families Nexus will support."""

    def __init__(self) -> None:
        self._profiles: dict[str, TechnologyProfile] = {
            "compute.linux": TechnologyProfile(
                key="compute.linux",
                title="Servidor Linux",
                family="compute",
                vendor="generic-linux",
                summary="Servidores Linux accesibles normalmente por SSH para diagnóstico de sistema, servicios, procesos y logs.",
                access=AccessProfile(
                    key="ssh",
                    connector="ssh",
                    auth_modes=["password", "ssh_key", "vault_profile"],
                    observation_capabilities=[
                        "host.run_command",
                        "host.read_logs",
                        "service.status",
                        "filesystem.usage",
                        "process.list",
                    ],
                    action_capabilities=[
                        "service.restart",
                        "package.install",
                    ],
                    notes="Base operativa para distribuciones Linux genéricas.",
                ),
                default_target_kind="host",
                classification_hints=["linux", "ubuntu", "debian", "rhel", "centos", "rocky", "alma", "host"],
                tags=["ssh", "server", "compute"],
            ),
            "compute.windows": TechnologyProfile(
                key="compute.windows",
                title="Servidor Windows",
                family="compute",
                vendor="microsoft",
                summary="Servidores Windows orientados a diagnóstico por WinRM, PowerShell remoting o herramientas corporativas equivalentes.",
                access=AccessProfile(
                    key="winrm",
                    connector="winrm",
                    auth_modes=["domain_user", "local_user", "vault_profile"],
                    observation_capabilities=[
                        "host.run_powershell",
                        "service.status",
                        "eventlog.read",
                        "process.list",
                        "filesystem.usage",
                    ],
                    action_capabilities=[
                        "service.restart",
                        "scheduled_task.run",
                    ],
                    notes="Pensado para operaciones remotas controladas sobre Windows Server.",
                ),
                default_target_kind="host",
                classification_hints=["windows", "winrm", "powershell", "event viewer", "iis", "microsoft"],
                tags=["winrm", "server", "compute"],
            ),
            "network.firewall.fortinet": TechnologyProfile(
                key="network.firewall.fortinet",
                title="Firewall Fortinet",
                family="network.firewall",
                vendor="fortinet",
                summary="Firewalls FortiGate con acceso preferente por API o CLI para revisar estado, sesiones, rutas y eventos de seguridad.",
                access=AccessProfile(
                    key="fortios-api",
                    connector="fortinet",
                    auth_modes=["api_token", "admin_profile", "ssh_fallback"],
                    observation_capabilities=[
                        "firewall.system_status",
                        "firewall.interface_status",
                        "firewall.route_table",
                        "firewall.session_overview",
                        "firewall.event_logs",
                    ],
                    action_capabilities=[
                        "firewall.clear_session",
                        "firewall.toggle_policy",
                    ],
                    notes="La API debe ser la vía principal; SSH/CLI queda como respaldo controlado.",
                ),
                default_target_kind="firewall",
                classification_hints=["fortinet", "fortigate", "fortios", "vdom", "policy", "utm"],
                tags=["network", "firewall", "security"],
            ),
            "network.switch.cisco": TechnologyProfile(
                key="network.switch.cisco",
                title="Switch Cisco",
                family="network.switch",
                vendor="cisco",
                summary="Switches Cisco con acceso por SSH/CLI o APIs de automatización para revisar interfaces, spanning tree, VLANs y consumo.",
                access=AccessProfile(
                    key="network-cli",
                    connector="cisco",
                    auth_modes=["ssh_password", "ssh_key", "tacacs_profile"],
                    observation_capabilities=[
                        "switch.show_interfaces",
                        "switch.show_mac_table",
                        "switch.show_spanning_tree",
                        "switch.show_cpu",
                        "switch.show_logs",
                    ],
                    action_capabilities=[
                        "switch.bounce_interface",
                        "switch.clear_counters",
                    ],
                    notes="Primera preparación orientada a Cisco IOS / IOS-XE por CLI.",
                ),
                default_target_kind="switch",
                classification_hints=["cisco", "switch", "ios", "ios-xe", "vlan", "port-channel", "spanning-tree"],
                tags=["network", "switch", "cisco"],
            ),
        }

    def get(self, key: str) -> TechnologyProfile | None:
        return self._profiles.get(key)

    def all(self) -> list[TechnologyProfile]:
        return list(self._profiles.values())

    def ids(self) -> list[str]:
        return list(self._profiles.keys())
