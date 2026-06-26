"""Technology-aware investigation planning for pre-diagnostic workflows."""

from __future__ import annotations

from typing import Any

from nexus.targets.catalogue import TechnologyCatalogue
from nexus.targets.classifier import TechnologyResolution


class TechnologyInvestigationPlanner:
    """Builds the first investigation frame for a classified technology family."""

    def __init__(self, catalogue: TechnologyCatalogue | None = None) -> None:
        self.catalogue = catalogue or TechnologyCatalogue()

    def build(self, resolution: TechnologyResolution, *, user_message: str) -> dict[str, Any]:
        profile = self.catalogue.get(resolution.technology_key)
        if profile is None:
            return {
                "technology_key": resolution.technology_key,
                "summary": "Tecnología no catalogada todavía.",
                "steps": [],
                "access": {},
                "capabilities": [],
            }

        summary = (
            f"{profile.title} detectado con acceso previsto {profile.access.key}. "
            f"Objetivo sugerido: {resolution.target_hint or 'sin objetivo resuelto'}."
        )
        return {
            "technology_key": profile.key,
            "title": profile.title,
            "summary": summary,
            "family": profile.family,
            "vendor": profile.vendor,
            "access": profile.access.to_dict(),
            "capabilities": list(profile.access.observation_capabilities),
            "steps": self._base_steps(profile.key, target_hint=resolution.target_hint),
            "risk_posture": self._risk_posture(profile.key),
            "user_message": user_message,
        }

    def _base_steps(self, technology_key: str, *, target_hint: str | None) -> list[str]:
        common = [
            f"Confirmar el activo objetivo {target_hint or 'a partir de la alerta o inventario'}.",
            "Validar que el metodo de acceso previsto esta disponible y con credenciales correctas.",
        ]
        if technology_key == "compute.linux":
            return common + [
                "Recoger carga, memoria, disco, procesos y estado de servicios.",
                "Leer logs recientes del servicio o del sistema relacionados con la alarma.",
                "Decidir si el problema parece de recurso, proceso, red o aplicacion.",
            ]
        if technology_key == "compute.windows":
            return common + [
                "Revisar estado de servicios, Event Viewer y procesos principales.",
                "Comprobar IIS o Scheduled Tasks si la alarma apunta a middleware Microsoft.",
                "Decidir si el problema parece de servicio, recurso o dependencia.",
            ]
        if technology_key == "network.firewall.fortinet":
            return common + [
                "Revisar estado general del firewall, interfaces y tabla de rutas.",
                "Consultar sesiones, eventos y politicas relacionadas con el trafico afectado.",
                "Determinar si el impacto viene de conectividad, policy o sobrecarga.",
            ]
        if technology_key == "network.switch.cisco":
            return common + [
                "Revisar interfaces, errores, spanning-tree y contexto de VLAN o port-channel.",
                "Consultar logs y consumo de CPU si la alarma apunta a flapping o saturacion.",
                "Determinar si el problema es fisico, de capa 2, de topologia o de configuracion.",
            ]
        return common

    def _risk_posture(self, technology_key: str) -> str:
        if technology_key.startswith("network.firewall"):
            return "high_control"
        if technology_key.startswith("network.switch"):
            return "high_control"
        return "observe_first"
