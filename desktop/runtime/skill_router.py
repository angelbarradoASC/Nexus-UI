"""Desktop skill router for the local assistant runtime."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from desktop.runtime.capabilities import PermissionLevel
from desktop.runtime.skills import DesktopSkill, DesktopSkillCatalogue
from nexus.prompts import resolve_prompt_sync
from nexus.utils.llm_json import parse_llm_json

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
        "monitoring.estado": [],
        "ssh.diagnostico": ["desktop.commands.run"],
        "docker.prediagnostico": ["desktop.docker.inspect"],
        "linux.prediagnostico": ["infra.linux.observe"],
        "windows.prediagnostico": ["infra.windows.observe"],
        "fortinet.prediagnostico": ["infra.fortinet.observe"],
        "cisco.switch.prediagnostico": ["infra.cisco.observe"],
        "web.busqueda": [],
        "sales.prospecting": [],
        "desktop.mouse_speed": ["desktop.system.control"],
        "desktop.system_task": ["desktop.system.control"],
        "general.respuesta": [],
    }

    _SKILL_PERMISSION = {
        "fichaje.entrada": PermissionLevel.ASSIST,
        "fichaje.salida": PermissionLevel.ASSIST,
        "assets.crear_ticket_operador": PermissionLevel.ASSIST,
        "jira.crear_ticket": PermissionLevel.ASSIST,
        "jira.consultar_ticket": PermissionLevel.ASSIST,
        "monitoring.estado": PermissionLevel.OBSERVE,
        "ssh.diagnostico": PermissionLevel.OPERATE,
        "docker.prediagnostico": PermissionLevel.ASSIST,
        "linux.prediagnostico": PermissionLevel.ASSIST,
        "windows.prediagnostico": PermissionLevel.ASSIST,
        "fortinet.prediagnostico": PermissionLevel.ASSIST,
        "cisco.switch.prediagnostico": PermissionLevel.ASSIST,
        "web.busqueda": PermissionLevel.ASSIST,
        "sales.prospecting": PermissionLevel.ASSIST,
        "desktop.mouse_speed": PermissionLevel.OPERATE,
        "desktop.system_task": PermissionLevel.OPERATE,
        "general.respuesta": PermissionLevel.ASSIST,
    }

    def __init__(
        self,
        catalogue: DesktopSkillCatalogue | None = None,
        *,
        settings_store: Any | None = None,
    ) -> None:
        self.catalogue = catalogue or DesktopSkillCatalogue()
        self._settings_store = settings_store

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

    async def resolve_llm(
        self,
        user_input: str,
        llm_router,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> SkillResolution:
        """Resolve intent via LLM classification (pepo.skill_intention).

        `history` (formato OpenAI, ultimos turnos) se incluye para poder
        resolver referencias como "hazlo", "bajala a la mitad", que solo
        tienen sentido en el contexto del turno anterior.

        Falls back to the heuristic resolve() on any LLM failure, invalid
        skill_id, or timeout — never raises.
        """
        text = user_input.strip()
        entities = self._extract_entities(text)
        system_prompt = resolve_prompt_sync("pepo.skill_intention").replace(
            "__SKILLS_CATALOGUE__", self.catalogue.as_prompt_options()
        )
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": text})
        try:
            response = await asyncio.wait_for(
                llm_router.call(
                    messages=messages,
                    # L1 tiene un modelo gratuito que OpenRouter retiro (404 en cada
                    # intento) — el router escala igualmente, pero el retry se come
                    # el timeout de 10s de aqui abajo y se acaba cayendo al heuristico.
                    preferred_level=2,
                    temperature=0.0,
                    # El modelo de L2 (nvidia/nemotron-nano-9b-v2:free) es "reasoning":
                    # gasta ~600 tokens pensando antes de escribir el JSON. Con 300 se
                    # cortaba a mitad de razonamiento y nunca llegaba a emitir el JSON.
                    max_tokens=900,
                    timeout=14.0,
                ),
                timeout=18.0,
            )
        except Exception:
            return self.resolve(user_input)

        if getattr(response, "error", None):
            return self.resolve(user_input)

        parsed = parse_llm_json(response.content or "")
        skill_id = (parsed or {}).get("skill_id")
        if not skill_id or skill_id not in self._SKILL_PERMISSION:
            return self.resolve(user_input)

        confidence = float(parsed.get("confidence", 0.5))
        rationale = parsed.get("rationale", "Clasificado por LLM (pepo.skill_intention).")
        llm_entities = parsed.get("entities")
        if isinstance(llm_entities, dict):
            entities = {**entities, **{k: v for k, v in llm_entities.items() if v}}
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
        if any(term in lowered for term in ("hay incidentes", "hay alertas", "hay alarmas", "que incidentes", "que alertas", "algun incidente", "alguna alerta", "estado de las alertas", "estado de los incidentes")):
            return "monitoring.estado", 0.93, "Pregunta por el estado actual de alertas/incidentes, sin pedir crear nada."
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
        if any(term in lowered for term in ("raton", "ratón", "mouse", "cursor", "puntero")) and any(
            term in lowered for term in ("velocidad", "sensibilidad", "rapido", "rápido", "lento", "va lento", "va rapido")
        ):
            return "desktop.mouse_speed", 0.85, "La peticion pide ajustar la velocidad del raton de este ordenador."
        if any(term in lowered for term in ("busca", "buscar", "encuentra", "dame el listado", "listado de")) and (
            "cerca de" in lowered
            or any(
                term in lowered
                for term in (
                    "asesor", "gestor", "fiscal", "laboral", "contable", "clinica",
                    "dentista", "odont", "inmobiliaria", "pisos", "alquiler",
                    "restaurante", "hosteleria", "peluquer", "taller", "gimnasio",
                    "empresas", "negocios", "leads", "clientes potenciales",
                    "prospeccion", "prospección",
                )
            )
        ):
            return "sales.prospecting", 0.9, "La peticion busca localizar empresas/negocios — encaja con prospeccion comercial (Sales)."
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
            "direction": None,
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
        entities["direction"] = self._detect_direction(text.lower())
        return entities

    @staticmethod
    def _detect_direction(lowered: str) -> str | None:
        if any(term in lowered for term in ("al maximo", "al máximo", "lo mas rapido", "lo más rápido")):
            return "max"
        if any(term in lowered for term in ("al minimo", "al mínimo", "lo mas lento", "lo más lento")):
            return "min"
        if any(term in lowered for term in ("por defecto", "valor normal", "resetea", "restablece")):
            return "reset"
        if any(term in lowered for term in ("sube", "aumenta", "mas rapido", "más rápido", "va lento")):
            return "up"
        if any(term in lowered for term in ("baja", "reduce", "disminuye", "mas lento", "más lento", "va rapido", "va rápido")):
            return "down"
        return None

    def _build_resolution(
        self,
        skill_id: str,
        confidence: float,
        rationale: str,
        entities: dict,
    ) -> SkillResolution:
        override = self._settings_store.get_override(skill_id) if self._settings_store else None
        if override and override.get("enabled") is False and skill_id != "general.respuesta":
            return self._build_resolution(
                "general.respuesta", 0.35,
                f"Skill '{skill_id}' desactivado desde el gestor de agentes.",
                entities,
            )

        permission_value = override.get("permission_level") if override else None
        permission = (
            PermissionLevel(permission_value)
            if permission_value is not None
            else self._SKILL_PERMISSION.get(skill_id, PermissionLevel.ASSIST)
        )
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
