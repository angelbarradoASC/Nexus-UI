"""Capability registry for the desktop assistant runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum


class PermissionLevel(IntEnum):
    """Permission boundary for local desktop capabilities."""

    OBSERVE = 0
    ASSIST = 1
    OPERATE = 2
    ADMIN = 3


@dataclass(slots=True)
class Capability:
    """A local capability that the assistant may invoke on desktop."""

    key: str
    title: str
    description: str
    permission_level: PermissionLevel
    category: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["permission_level"] = int(self.permission_level)
        payload["permission_name"] = self.permission_level.name.lower()
        return payload


class CapabilityRegistry:
    """Stores and exposes desktop capabilities for the local assistant."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.key] = capability

    def get(self, key: str) -> Capability | None:
        return self._capabilities.get(key)

    def list_all(self) -> list[Capability]:
        return sorted(self._capabilities.values(), key=lambda item: item.key)

    def list_enabled(self) -> list[Capability]:
        return [item for item in self.list_all() if item.enabled]

    def list_by_permission(self, level: PermissionLevel) -> list[Capability]:
        return [
            item for item in self.list_enabled()
            if item.permission_level <= level
        ]

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self._capabilities),
            "enabled": len(self.list_enabled()),
            "observe": len(self.list_by_permission(PermissionLevel.OBSERVE)),
            "assist": len(self.list_by_permission(PermissionLevel.ASSIST)),
            "operate": len(self.list_by_permission(PermissionLevel.OPERATE)),
            "admin": len(self.list_by_permission(PermissionLevel.ADMIN)),
        }


def build_default_registry() -> CapabilityRegistry:
    """Seed the runtime with the first useful desktop-local capabilities."""
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            key="desktop.metrics.read",
            title="Lectura de metricas locales",
            description="Lee CPU, memoria, disco y red del equipo local.",
            permission_level=PermissionLevel.OBSERVE,
            category="observability",
            tags=["desktop", "metrics", "hardware"],
        )
    )
    registry.register(
        Capability(
            key="desktop.processes.read",
            title="Lectura de procesos",
            description="Lista procesos y su consumo de recursos en el equipo local.",
            permission_level=PermissionLevel.OBSERVE,
            category="observability",
            tags=["desktop", "process", "diagnostics"],
        )
    )
    registry.register(
        Capability(
            key="desktop.tray.quick_action",
            title="Quick actions del tray",
            description="Lanza acciones directas seguras desde el tray local.",
            permission_level=PermissionLevel.ASSIST,
            category="actions",
            tags=["desktop", "tray", "automation"],
        )
    )
    registry.register(
        Capability(
            key="desktop.files.read",
            title="Lectura de ficheros locales",
            description="Permite inspeccionar ficheros locales dentro de las políticas aprobadas.",
            permission_level=PermissionLevel.ASSIST,
            category="filesystem",
            tags=["desktop", "files"],
        )
    )
    registry.register(
        Capability(
            key="desktop.commands.run",
            title="Ejecucion de comandos locales",
            description="Ejecuta comandos locales con control y trazabilidad.",
            permission_level=PermissionLevel.OPERATE,
            category="execution",
            tags=["desktop", "command", "ops"],
        )
    )
    registry.register(
        Capability(
            key="desktop.docker.inspect",
            title="Inspeccion de Docker local",
            description="Recoge estado, logs y metadatos basicos de contenedores Docker en local.",
            permission_level=PermissionLevel.ASSIST,
            category="containers",
            tags=["desktop", "docker", "containers", "diagnostics"],
        )
    )
    registry.register(
        Capability(
            key="infra.linux.observe",
            title="Observacion de servidores Linux",
            description="Prepara y gobierna diagnosticos sobre hosts Linux por SSH y capacidades equivalentes.",
            permission_level=PermissionLevel.ASSIST,
            category="infrastructure",
            tags=["linux", "ssh", "server", "compute"],
        )
    )
    registry.register(
        Capability(
            key="infra.windows.observe",
            title="Observacion de servidores Windows",
            description="Prepara y gobierna diagnosticos sobre Windows Server por WinRM o PowerShell remoto.",
            permission_level=PermissionLevel.ASSIST,
            category="infrastructure",
            tags=["windows", "winrm", "server", "compute"],
        )
    )
    registry.register(
        Capability(
            key="infra.fortinet.observe",
            title="Observacion de Fortinet",
            description="Prepara diagnosticos de firewalls Fortinet por API o CLI controlada.",
            permission_level=PermissionLevel.ASSIST,
            category="network",
            tags=["fortinet", "firewall", "security", "network"],
        )
    )
    registry.register(
        Capability(
            key="infra.cisco.observe",
            title="Observacion de switches Cisco",
            description="Prepara diagnosticos de switches Cisco por SSH/CLI y futuras APIs de automatizacion.",
            permission_level=PermissionLevel.ASSIST,
            category="network",
            tags=["cisco", "switch", "network", "cli"],
        )
    )
    registry.register(
        Capability(
            key="desktop.apps.automate",
            title="Automatizacion de aplicaciones locales",
            description="Interactua con aplicaciones corporativas del puesto.",
            permission_level=PermissionLevel.ADMIN,
            category="automation",
            enabled=False,
            tags=["desktop", "gui", "future"],
        )
    )
    return registry
