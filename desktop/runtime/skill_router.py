"""Desktop skill router for the local assistant runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from desktop.runtime.capabilities import PermissionLevel
from desktop.runtime.skills import DesktopSkill, DesktopSkillCatalogue

_HOST_PATTERN = re.compile(r"\b(?:\d{1,3}(?:\.\d{1,3}){3}|[a-zA-Z0-9][\w.-]*\d+[\w.-]*)\b")
_TICKET_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_CONTAINER_PATTERN = re.compile(
    r"\b(?:contenedor|container|docker)\b(?:\s+(?:en|del|de|el|la))?\s+([a-zA-Z0-9][\w.-]*)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class SkillResolution:
    """Result of resolving a desktop-local user intent into a skill candidate."""

    skill_id: str
    confidence: float
    rationale: str
    entities: dict = field(default_factory=dict)
    required_capabilities: list[str] = field(default_factory=list)
    permission_level: int = int(PermissionLevel.ASSIST)
    needs_confirmation: bool = False
    execution_mode: str = "assist"

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "entities": self.entities,
            "required_capabilities": self.required_capabilities,
            "permission_level": self.permission_level,
            "needs_confirmation": self.needs_confirmation,
            "execution_mode": self.execution_mode,
        }


class DesktopSkillRouter:
    """Maps user requests to the shared skill catalogue plus desktop capabilities."""

    _SKILL_CAPABILITIES = {
        "fichaje.entrada": ["desktop.tray.quick_action"],
        "fichaje.salida": ["desktop.tray.quick_action"],
        "assets.crear_ticket_operador": [],
        "jira.crear_ticket": [],
        "jira.consultar_ticket": [],
        "ssh.diagnostico": ["desktop.commands.run"],
        "docker.prediagnostico": ["desktop.docker.inspect"],
        "linux.prediagnostico": ["infra.linux.observe"],
        "windows.prediagnostico": ["infra.windows.observe"],
        "fortinet.prediagnostico": ["infra.fortinet.observe"],
        "cisco.switch.prediagnostico": ["infra.cisco.observe"],
        "web.busqueda": [],
        "general.respuesta": [],
    }

    _SKILL_PERMISSION = {
        "fichaje.entrada": PermissionLevel.ASSIST,
        "fichaje.salida": PermissionLevel.ASSIST,
        "assets.crear_ticket_operador": PermissionLevel.ASSIST,
        "jira.crear_ticket": PermissionLevel.ASSIST,
        "jira.consultar_ticket": PermissionLevel.ASSIST,
        "ssh.diagnostico": PermissionLevel.OPERATE,
        "docker.prediagnostico": PermissionLevel.ASSIST,
        "linux.prediagnostico": PermissionLevel.ASSIST,
        "windows.prediagnostico": PermissionLevel.ASSIST,
        "fortinet.prediagnostico": PermissionLevel.ASSIST,
        "cisco.switch.prediagnostico": PermissionLevel.ASSIST,
        "web.busqueda": PermissionLevel.ASSIST,
        "general.respuesta": PermissionLevel.ASSIST,
    }

    def __init__(self, catalogue: DesktopSkillCatalogue | None = None) -> None:
        self.catalogue = catalogue or DesktopSkillCatalogue()

    def resolve(self, user_input: str) -> SkillResolution:
        text = user_input.strip()
        lowered = text.lower()
        entities = self._extract_entities(text)

        skill_id, confidence, rationale = self._heuristic_match(lowered, entities)
        if skill_id is None:
            scored = self._score_against_catalogue(lowered)
            if scored is not None:
                skill_id, confidence, rationale = scored
            else:
                skill_id = "general.respuesta"
                confidence = 0.35
                rationale = "No hay una coincidencia operativa clara; se trata como asistencia general."

        return self._build_resolution(skill_id, confidence, rationale, entities)

    def _heuristic_match(
        self,
        lowered: str,
        entities: dict,
    ) -> tuple[str | None, float, str]:
        if any(term in lowered for term in ("ficha mi entrada", "acabo de llegar", "empiezo la jornada", "ya he llegado")):
            return "fichaje.entrada", 0.98, "La peticion encaja con una accion de fichaje de entrada."
        if any(term in lowered for term in ("ficha mi salida", "me voy a casa", "termino la jornada", "salgo ya")):
            return "fichaje.salida", 0.98, "La peticion encaja con una accion de fichaje de salida."
        if entities.get("ticket_id") and any(term in lowered for term in ("ticket", "estado", "como esta", "como esta", "consulta")):
            return "jira.consultar_ticket", 0.97, "Se ha detectado una consulta clara sobre un ticket existente."
        if any(term in lowered for term in ("crear ticket", "crea ticket", "crea un ticket", "abre ticket", "abre un ticket", "abrir ticket", "abre una incidencia", "registra incidencia", "escalalo a ticket", "escalalo como ticket")) and any(
            term in lowered
            for term in (
                "alarma",
                "alerta",
                "monitor",
                "monitorizacion",
                "grafana",
                "prometheus",
                "alertmanager",
                "servidor",
                "host",
                "contenedor",
                "docker",
                "caido",
                "falla",
                "error",
                "operador",
                "assets",
                "ia ",
                " ia",
            )
        ):
            return "assets.crear_ticket_operador", 0.94, "La peticion encaja con la apertura de un ticket operativo en Assets."
        if "ticket" in lowered and any(term in lowered for term in ("crea", "abre", "incidencia", "jira")):
            return "jira.crear_ticket", 0.91, "La peticion describe la apertura o preparacion de un ticket."
        if any(term in lowered for term in ("docker", "contenedor", "container", "compose")) and (
            any(term in lowered for term in ("alarma", "alerta", "diagnost", "revisa", "analiza", "caido", "falla"))
            or entities.get("container")
        ):
            return "docker.prediagnostico", 0.95, "La peticion parece un pre diagnostico sobre un contenedor Docker."
        if any(term in lowered for term in ("linux", "ubuntu", "debian", "rhel", "centos", "rocky", "alma")) and (
            any(term in lowered for term in ("alarma", "alerta", "diagnost", "revisa", "analiza", "lento", "caido", "cpu", "memoria", "disco"))
            or entities.get("servidor")
        ):
            return "linux.prediagnostico", 0.93, "La peticion parece un pre diagnostico sobre un servidor Linux."
        if any(term in lowered for term in ("windows", "winrm", "powershell", "iis", "event viewer", "eventlog")) and (
            any(term in lowered for term in ("alarma", "alerta", "diagnost", "revisa", "analiza", "servicio", "app pool"))
            or entities.get("servidor")
        ):
            return "windows.prediagnostico", 0.93, "La peticion parece un pre diagnostico sobre un servidor Windows."
        if any(term in lowered for term in ("fortinet", "fortigate", "fortios")) and any(
            term in lowered for term in ("alarma", "alerta", "diagnost", "revisa", "firewall", "cortes", "policy")
        ):
            return "fortinet.prediagnostico", 0.94, "La peticion parece un pre diagnostico sobre un firewall Fortinet."
        if any(term in lowered for term in ("switch cisco", "cisco nexus", "cisco ios", "vlan", "spanning tree", "puerto")) and any(
            term in lowered for term in ("alarma", "alerta", "diagnost", "revisa", "caido", "flapping", "core")
        ):
            return "cisco.switch.prediagnostico", 0.94, "La peticion parece un pre diagnostico sobre switching Cisco."
        if any(term in lowered for term in ("diagnost", "revisa", "analiza", "como esta", "que pasa")) and entities.get("servidor"):
            return "ssh.diagnostico", 0.93, "La peticion parece un diagnostico tecnico sobre un activo concreto."
        if any(term in lowered for term in ("cpu", "memoria", "disco", "red", "logs", "alerta", "incidencia")) and entities.get("servidor"):
            return "ssh.diagnostico", 0.88, "Hay senales de diagnostico operativo con objetivo identificado."
        if any(term in lowered for term in ("busca", "precio", "noticias", "documentacion", "version reciente", "ultima version", "hoy")):
            return "web.busqueda", 0.84, "La peticion requiere informacion externa o potencialmente reciente."
        return None, 0.0, ""

    def _score_against_catalogue(self, lowered: str) -> tuple[str, float, str] | None:
        best_skill: DesktopSkill | None = None
        best_score = 0
        for skill in self.catalogue.all():
            score = 0
            for trigger in skill.triggers:
                trigger_lower = trigger.lower()
                if trigger_lower in lowered:
                    score += 4
                else:
                    overlap = len(set(trigger_lower.split()) & set(lowered.split()))
                    score += overlap
            for example in skill.examples[:2]:
                example_lower = example.lower()
                overlap = len(set(example_lower.split()) & set(lowered.split()))
                score += overlap
            if score > best_score:
                best_score = score
                best_skill = skill
        if best_skill is None or best_score <= 0:
            return None
        confidence = min(0.4 + (best_score * 0.08), 0.89)
        rationale = f"Coincidencia por catalogo con triggers del skill {best_skill.skill_id}."
        return best_skill.skill_id, round(confidence, 2), rationale

    def _extract_entities(self, text: str) -> dict:
        entities: dict[str, str | None] = {
            "servidor": None,
            "ticket_id": None,
            "container": None,
        }
        host_match = _HOST_PATTERN.search(text)
        if host_match:
            value = host_match.group(0)
            if not value.isdigit():
                entities["servidor"] = value
        container_matches = list(_CONTAINER_PATTERN.finditer(text))
        if container_matches:
            entities["container"] = container_matches[-1].group(1)
        ticket_match = _TICKET_PATTERN.search(text.upper())
        if ticket_match:
            entities["ticket_id"] = ticket_match.group(0)
        return entities

    def _build_resolution(
        self,
        skill_id: str,
        confidence: float,
        rationale: str,
        entities: dict,
    ) -> SkillResolution:
        permission = self._SKILL_PERMISSION.get(skill_id, PermissionLevel.ASSIST)
        capabilities = list(self._SKILL_CAPABILITIES.get(skill_id, []))
        execution_mode = "assist"
        needs_confirmation = False
        if permission >= PermissionLevel.OPERATE:
            execution_mode = "guided_diagnostic"
            needs_confirmation = True
        elif skill_id in {
            "docker.prediagnostico",
            "linux.prediagnostico",
            "windows.prediagnostico",
            "fortinet.prediagnostico",
            "cisco.switch.prediagnostico",
        }:
            execution_mode = "guided_observation"
        return SkillResolution(
            skill_id=skill_id,
            confidence=round(confidence, 2),
            rationale=rationale,
            entities={key: value for key, value in entities.items() if value},
            required_capabilities=capabilities,
            permission_level=int(permission),
            needs_confirmation=needs_confirmation,
            execution_mode=execution_mode,
        )
