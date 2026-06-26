"""
app/agents/intention_agent.py
------------------------------
Clasifica la intención del usuario y extrae entidades via LLM.

Usa L0/L1 (temperatura 0) — barato y determinista.
Devuelve siempre IntentionResult (nunca lanza excepciones al orquestador).
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from nexus.prompts import resolve_prompt_sync

from .base_agent import AgentResult, BaseAgent

# ── Enums ─────────────────────────────────────────────────────────────────────

class Intencion(StrEnum):
    DIAGNOSTICO_SERVIDOR = "diagnostico_servidor"
    CREAR_TICKET_JIRA    = "crear_ticket_jira"
    BUSQUEDA_WEB         = "busqueda_web"
    GENERAL              = "general"


# ── Modelos de resultado ──────────────────────────────────────────────────────

class IntentionResult(BaseModel):
    """Resultado de la clasificación de intención."""
    intention: Intencion = Intencion.GENERAL
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    missing_required: list[str] = Field(default_factory=list)
    follow_up_question: str | None = None


# ── Prompt del sistema ────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Eres un clasificador de intenciones para un motor de agentes autónomos.

Analiza la consulta del usuario y devuelve SOLO un objeto JSON (sin texto adicional) con:
- intention: una de estas opciones:
  * "diagnostico_servidor" — si quiere diagnosticar/revisar/analizar un servidor
  * "crear_ticket_jira"   — si quiere crear, consultar o comentar un ticket en Jira
  * "busqueda_web"        — si necesita buscar información en internet
  * "general"             — conversación, preguntas que el LLM puede responder

- entities: objeto con datos extraídos (null si no se menciona):
  * servidor      — nombre o IP del servidor
  * problema      — tipo: cpu / memoria / disco / red / logs
  * ticket_id     — clave del ticket (ej: "NEXUS-42")
  * resumen       — resumen del ticket a crear
  * descripcion   — descripción del ticket
  * tipo_ticket   — Task / Bug / Story
  * accion        — "crear" o "consultar" (solo Jira)
  * search_query  — query optimizada para la web

- confidence: número entre 0 y 1

REGLA busqueda_web: úsala para información reciente o que el LLM no puede conocer: noticias, precios, clima, documentación de versiones recientes, estado de servicios, etc.

Ejemplos:
Usuario: "revisa el servidor web-prod-01"
{"intention":"diagnostico_servidor","entities":{"servidor":"web-prod-01","problema":null,"ticket_id":null,"resumen":null,"descripcion":null,"tipo_ticket":null,"accion":null,"search_query":null},"confidence":0.95}

Usuario: "crea un ticket: el servicio de pagos está caído"
{"intention":"crear_ticket_jira","entities":{"servidor":null,"problema":null,"ticket_id":null,"resumen":"El servicio de pagos está caído","descripcion":"El servicio de pagos está caído","tipo_ticket":"Bug","accion":"crear","search_query":null},"confidence":0.92}

Usuario: "busca el precio del bitcoin"
{"intention":"busqueda_web","entities":{"servidor":null,"problema":null,"ticket_id":null,"resumen":null,"descripcion":null,"tipo_ticket":null,"accion":null,"search_query":"precio bitcoin hoy"},"confidence":0.98}

Usuario: "hola, ¿cómo estás?"
{"intention":"general","entities":{"servidor":null,"problema":null,"ticket_id":null,"resumen":null,"descripcion":null,"tipo_ticket":null,"accion":null,"search_query":null},"confidence":0.99}

Devuelve SOLO el JSON, sin markdown ni explicaciones."""


# ── Agente ────────────────────────────────────────────────────────────────────

class IntentionAgent(BaseAgent):
    """
    Clasifica la intención y extrae entidades.
    Usa L0/L1 con temperatura=0 para respuestas deterministas.
    """

    async def ejecutar(
        self,
        consulta: str,
        entidades: dict[str, Any],
        historial: list[dict[str, str]],
    ) -> AgentResult:
        """Interfaz BaseAgent — llama a classify() internamente."""
        result = await self.classify(consulta, historial)
        return AgentResult(
            respuesta=result.follow_up_question or "",
            exito=True,
            agente=self._nombre(),
            datos=result.model_dump(),
        )

    async def classify(
        self,
        user_query: str,
        historial: list[dict[str, str]] | None = None,
    ) -> IntentionResult:
        """
        Clasifica la intención del usuario.
        Acepta historial opcional para resolver intenciones ambiguas en contexto.
        Devuelve IntentionResult con fallback a 'general' si falla.
        """
        llm_raw = ""
        try:
            messages: list[dict[str, str]] = [
                {"role": "system", "content": resolve_prompt_sync("agent.intention")},
            ]
            # Incluir los últimos 4 turnos del historial para dar contexto al clasificador
            if historial:
                messages.extend(historial[-4:])
            messages.append({"role": "user", "content": user_query})
            result = await self.router.call(
                messages,
                min_level=0,
                preferred_level=1,   # L1 preferido: rápido y JSON limpio
                speed_level=2,
                temperature=0.0,     # Determinista para clasificación
                max_tokens=400,
                timeout=30.0,
            )

            if result.error:
                logger.error("IntentionAgent error router | error={}", result.error)
                return self._fallback()

            llm_raw = result.content
            classification_raw = self._parsear_json(llm_raw)

            # Normalizar intención
            raw_intention = classification_raw.get("intention", "general")
            try:
                intention = Intencion(raw_intention)
            except ValueError:
                logger.warning(
                    "IntentionAgent: intención desconocida '{}', usando general",
                    raw_intention,
                )
                intention = Intencion.GENERAL

            entities: dict[str, Any] = classification_raw.get("entities") or {}
            confidence: float = float(classification_raw.get("confidence", 0.0))

            missing, follow_up = self._validar(intention, entities)

            ir = IntentionResult(
                intention=intention,
                entities=entities,
                confidence=confidence,
                missing_required=missing,
                follow_up_question=follow_up,
            )

            logger.info(
                "IntentionAgent | intencion={} | confianza={:.2f} | entidades={}",
                ir.intention,
                ir.confidence,
                {k: v for k, v in ir.entities.items() if v is not None},
            )
            return ir

        except json.JSONDecodeError as e:
            logger.error(
                "IntentionAgent JSON inválido | error={} | raw={!r:.200}",
                e, llm_raw,
            )
            return self._fallback()

        except Exception:
            logger.exception("IntentionAgent error inesperado")
            return self._fallback()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parsear_json(texto: str) -> dict[str, Any]:
        """Extrae JSON de la respuesta con tolerancia a bloques markdown."""
        texto = texto.strip()

        # Intento directo
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            pass

        # Extraer de bloque ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", texto)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Extraer primer objeto JSON que encuentre
        match = re.search(r"\{[\s\S]+\}", texto)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError("No se encontró JSON válido", texto, 0)

    @staticmethod
    def _validar(
        intention: Intencion,
        entities: dict[str, Any],
    ) -> tuple[list[str], str | None]:
        """Detecta datos obligatorios faltantes y genera pregunta de seguimiento."""
        missing: list[str] = []
        follow_up: str | None = None

        if intention == Intencion.DIAGNOSTICO_SERVIDOR and not entities.get("servidor"):
            missing.append("servidor")
            follow_up = "¿Qué servidor quieres diagnosticar? (nombre o IP)"

        if intention == Intencion.CREAR_TICKET_JIRA:
            accion = entities.get("accion", "crear")
            if accion == "consultar" and not entities.get("ticket_id"):
                missing.append("ticket_id")
                follow_up = "¿Cuál es la clave del ticket? (ej: NEXUS-42)"
            elif accion == "crear" and not entities.get("resumen"):
                missing.append("resumen")
                follow_up = "¿Cuál es el título del ticket que quieres crear?"

        return missing, follow_up

    @staticmethod
    def _fallback() -> IntentionResult:
        return IntentionResult(
            intention=Intencion.GENERAL,
            confidence=0.0,
        )
