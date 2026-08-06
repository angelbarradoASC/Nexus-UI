"""Central coordinator for Nexus workflows."""

from __future__ import annotations

import json
import uuid
from typing import Any

from agents.generation_agent import GenerationAgent
from desktop.runtime.skill_router import DesktopSkillRouter
from nexus.audit.models import AuditEntry
from nexus.api.schemas.chat import ChatRequest, ChatResponse
from nexus.api.schemas.incidents import IncidentIngestRequest, IncidentListResponse, IncidentResponse
from nexus.api.schemas.monitoring import (
    AlertSilenceRequest,
    AlertSilenceResponse,
    AlertWebhookRequest,
    AlertWebhookResponse,
    AlertsResponse,
    MetricsIngestRequest,
    MetricsIngestResponse,
    PrometheusQueryRequest,
    PrometheusQueryResponse,
    RunbooksResponse,
)
from nexus.audit.repository import MemoryAuditRepository
from nexus.connectors.itsm.jira import JiraConnector
from nexus.connectors.observability.alertmanager import AlertmanagerConnector
from nexus.connectors.observability.grafana import GrafanaConnector
from nexus.connectors.observability.prometheus import PrometheusConnector
from nexus.domain.entities.tool_action import ToolAction
from nexus.execution.executor import ExecutionExecutor
from nexus.incidents.repository import MemoryIncidentRepository
from nexus.incidents.incident_pipeline import IncidentPipeline
from nexus.diagnostics.docker_pre_diagnostic import DockerPreDiagnosticService
from nexus.investigation.technology_plan import TechnologyInvestigationPlanner
from nexus.monitoring.alert_pipeline import AlertPipeline
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.operations import AssetsOperationsService
from nexus.policy.guardrails import can_auto_execute, should_create_ticket
from nexus.prompts import resolve_prompt_sync
from nexus.prospecting import ProspectingAgentService
from nexus.targets.classifier import TechnologyClassifier
from nexus.workers.registry import list_workers


class NexusCoordinator:
    """Coordinates the first production-minded Nexus v1 workflows."""

    def __init__(
        self,
        alertmanager: AlertmanagerConnector,
        grafana: GrafanaConnector,
        prometheus: PrometheusConnector,
        incident_repository: MemoryIncidentRepository,
        audit_repository: MemoryAuditRepository,
        runbooks: RunbookRegistry,
        llm_router: Any | None = None,
        docker_diagnostics: DockerPreDiagnosticService | None = None,
        operations: AssetsOperationsService | None = None,
        jira: JiraConnector | None = None,
        prospecting: ProspectingAgentService | None = None,
        mouse_agent: Any | None = None,
        system_task_agent: Any | None = None,
    ) -> None:
        self._alertmanager = alertmanager
        self._grafana = grafana
        self._prometheus = prometheus
        self._operations = operations
        self._jira = jira
        self._prospecting = prospecting
        self._mouse_agent = mouse_agent
        self._system_task_agent = system_task_agent
        self._incident_repository = incident_repository
        self._audit_repository = audit_repository
        self._runbooks = runbooks
        self._llm_router = llm_router
        self._skill_router = DesktopSkillRouter()
        self._technology_classifier = TechnologyClassifier()
        self._technology_planner = TechnologyInvestigationPlanner()
        self._docker_diagnostics = docker_diagnostics or DockerPreDiagnosticService()
        self._executor = ExecutionExecutor()
        self._incident_pipeline = IncidentPipeline()
        self._alert_pipeline = AlertPipeline(self._incident_pipeline)

    def use_persistence(self, incident_repository, audit_repository) -> None:
        """Swap repositories when a persistent backend becomes available."""
        self._incident_repository = incident_repository
        self._audit_repository = audit_repository

    async def health_snapshot(self) -> dict[str, object]:
        return {
            "status": "ok",
            "surface": "nexus-v1",
            "flows": ["chat", "incidents", "monitoring"],
            "workers": list_workers(),
        }

    async def handle_chat(
        self,
        payload: ChatRequest,
        *,
        resolution_override: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> ChatResponse:
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        context_key = payload.context_id or payload.user_id
        if self._mouse_agent is not None and self._mouse_agent.has_pending(context_key):
            return await self._handle_mouse_speed_pending(payload, audit_id, context_key)
        if self._system_task_agent is not None and self._system_task_agent.has_pending(context_key):
            return await self._handle_system_task_pending(payload, audit_id, context_key)
        resolution = resolution_override or self._skill_router.resolve(payload.message).to_dict()
        skill_id = resolution.get("skill_id", "general.respuesta")
        if skill_id == "desktop.mouse_speed" and self._mouse_agent is not None:
            return await self._handle_mouse_speed_propose(payload, resolution, audit_id, context_key)
        if skill_id == "desktop.system_task" and self._system_task_agent is not None:
            return await self._handle_system_task_propose(payload, audit_id, context_key)
        if skill_id == "assets.crear_ticket_operador" or (
            skill_id == "jira.crear_ticket"
            and payload.mode in {"operator", "monitoring", "incident"}
        ):
            return await self._handle_assets_ticket_chat(payload, resolution, audit_id)
        if skill_id == "docker.prediagnostico":
            return await self._handle_docker_prediagnostic_chat(payload, resolution, audit_id)
        if skill_id == "sales.prospecting" and self._prospecting is not None:
            return await self._handle_sales_prospecting_chat(payload, audit_id)
        if skill_id in {
            "linux.prediagnostico",
            "windows.prediagnostico",
            "fortinet.prediagnostico",
            "cisco.switch.prediagnostico",
        }:
            return await self._handle_technology_prediagnostic_chat(payload, audit_id)

        if self._llm_router is not None:
            result = await GenerationAgent(router=self._llm_router).ejecutar(
                payload.message,
                {
                    "mode": payload.mode,
                    "context_id": payload.context_id,
                    "skill_id": skill_id,
                    "skill_entities": resolution.get("entities", {}),
                },
                history or [],
            )
            response = result.respuesta
            status = "accepted" if result.exito else "degraded"
            agent_name = result.agente or "generation-agent"
            details = {
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "llm_error": result.error,
                "llm_agent": agent_name,
            }
        else:
            response = (
                "Nexus v1 ha recibido tu mensaje y lo ha clasificado en el flujo "
                f"'{payload.mode}'. Esta primera version prioriza orquestacion, "
                "monitorizacion e incidentes con control operativo."
            )
            status = "accepted"
            agent_name = "nexus-coordinator"
            details = {
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
            }
        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status=status,
            details=details,
            audit_id=audit_id,
        )
        return ChatResponse(
            status=status,
            response=response,
            agent=agent_name,
            flow="chat",
            audit_id=audit_id,
        )

    async def _handle_technology_prediagnostic_chat(
        self,
        payload: ChatRequest,
        audit_id: str,
    ) -> ChatResponse:
        resolution = self._technology_classifier.classify(payload.message)
        if resolution is None:
            await self._audit(
                flow="chat",
                action="handle_chat",
                actor=payload.user_id,
                status="degraded",
                details={
                    "mode": payload.mode,
                    "context_id": payload.context_id,
                    "message_preview": payload.message[:160],
                    "technology_key": "unknown",
                },
                audit_id=audit_id,
            )
            return ChatResponse(
                status="degraded",
                response=(
                    "No he podido clasificar con suficiente confianza la tecnología afectada. "
                    "Indícame si hablamos de Linux, Windows, Fortinet o Cisco."
                ),
                agent="technology-prediagnostic",
                flow="chat",
                audit_id=audit_id,
            )

        plan = self._technology_planner.build(resolution, user_message=payload.message)
        response = self._render_technology_plan(plan)
        status = "accepted"
        agent_name = "technology-prediagnostic"

        if self._llm_router is not None:
            llm_prompt = self._build_technology_llm_prompt(payload.message, plan)
            result = await GenerationAgent(router=self._llm_router).ejecutar(
                llm_prompt,
                {
                    "mode": payload.mode,
                    "technology_key": resolution.technology_key,
                    "target_hint": resolution.target_hint,
                },
                [],
            )
            if result.exito and result.respuesta:
                response = result.respuesta
                agent_name = result.agente or "GenerationAgent"
            else:
                status = "degraded"

        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status=status,
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "technology_key": resolution.technology_key,
                "target_hint": resolution.target_hint,
                "access_key": resolution.access_key,
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status=status,
            response=response,
            agent=agent_name,
            flow="chat",
            audit_id=audit_id,
        )

    async def _handle_sales_prospecting_chat(
        self,
        payload: ChatRequest,
        audit_id: str,
    ) -> ChatResponse:
        from nexus.api.routes.prospecting import ProspectingChatRequest, prospecting_chat
        from nexus.api.schemas.prospecting import ProspectingRunRequest

        result = await prospecting_chat(
            ProspectingChatRequest(message=payload.message, history=[]),
            prospecting=self._prospecting,
        )
        prospecting_status = result.get("status", "clarifying")
        reply = result.get("reply", "")
        brief = result.get("brief")

        run_id = None
        if prospecting_status == "ready" and brief:
            run_request = ProspectingRunRequest(
                vertical=brief.get("vertical", "custom"),
                target_description=brief.get("target_description", ""),
                city=brief.get("city", ""),
                province=brief.get("province", ""),
                region=brief.get("region", ""),
                desired_count=brief.get("desired_count", 20),
                must_have=brief.get("must_have", []),
                minimum_score=brief.get("minimum_score", 40),
                represented_by=brief.get("represented_by", "assets"),
                min_employees=brief.get("min_employees"),
                max_employees=brief.get("max_employees"),
                industrial_zone=brief.get("industrial_zone", ""),
                dry_run=False,
                async_mode=True,
            )
            run_result = await self._prospecting.run(run_request)
            run_id = run_result.get("run_id")
            if run_id:
                reply = f"{reply}\n\nBúsqueda lanzada en Sales (run {run_id}). Los resultados aparecerán en la pestaña Sales cuando termine."

        status = "accepted" if prospecting_status == "ready" else "degraded"
        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status=status,
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "skill_id": "sales.prospecting",
                "prospecting_status": prospecting_status,
                "run_id": run_id,
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status=status,
            response=reply or "¿En qué ciudad quieres buscar y qué tipo de negocio?",
            agent="sales-prospecting",
            flow="chat",
            audit_id=audit_id,
            run_id=run_id,
        )

    async def _handle_mouse_speed_propose(
        self,
        payload: ChatRequest,
        resolution: dict[str, Any],
        audit_id: str,
        context_key: str,
    ) -> ChatResponse:
        direction = (resolution.get("entities") or {}).get("direction") or "down"
        proposal = self._mouse_agent.propose_change(context_key, direction)
        response = (
            f"La velocidad actual del ratón es {proposal['current']} (escala 1-20). "
            f"Voy a ponerla en {proposal['target']}. ¿Confirmas?"
        )
        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status="accepted",
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "skill_id": "desktop.mouse_speed",
                "proposal": proposal,
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status="accepted",
            response=response,
            agent="desktop-mouse-agent",
            flow="chat",
            audit_id=audit_id,
        )

    async def _handle_mouse_speed_pending(
        self,
        payload: ChatRequest,
        audit_id: str,
        context_key: str,
    ) -> ChatResponse:
        lowered = payload.message.strip().lower()
        if any(w in lowered for w in ("si", "sí", "confirmo", "adelante", "dale", "hazlo", "vale", "ok")):
            result = self._mouse_agent.confirm(context_key)
            response = f"Hecho — velocidad del ratón cambiada de {result['previous']} a {result['applied']}."
        elif any(w in lowered for w in ("no", "cancela", "cancelar", "olvidalo", "olvídalo", "déjalo", "dejalo")):
            self._mouse_agent.cancel(context_key)
            response = "Vale, no toco nada."
        else:
            response = "¿Confirmas el cambio de velocidad del ratón que te propuse? (sí/no)"

        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status="accepted",
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "skill_id": "desktop.mouse_speed",
                "pending_resolution": response,
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status="accepted",
            response=response,
            agent="desktop-mouse-agent",
            flow="chat",
            audit_id=audit_id,
        )

    def _render_system_task_proposal(self, proposal: dict) -> str:
        kind = proposal.get("kind")
        if kind == "skill_match":
            return (
                f"Ya tengo un script guardado para esto ({proposal.get('description')}):\n"
                f"```\n{proposal.get('script')}\n```\n¿Confirmas que lo ejecute?"
            )
        if kind == "run_script":
            return (
                "No tengo esto guardado todavia, pero puedo resolverlo con este script:\n"
                f"```\n{proposal.get('script')}\n```\nSi funciona lo guardo para la proxima vez. ¿Confirmas?"
            )
        if kind == "ask_user":
            return proposal.get("question", "¿Puedes darme mas detalles?")
        if kind == "finish":
            return proposal.get("summary", "Hecho.")
        return f"Voy a hacer esto en tu PC: \"{proposal.get('task', '')}\". ¿Confirmas?"

    async def _handle_system_task_propose(
        self,
        payload: ChatRequest,
        audit_id: str,
        context_key: str,
    ) -> ChatResponse:
        proposal = await self._system_task_agent.propose(context_key, payload.message)
        response = self._render_system_task_proposal(proposal)

        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status="accepted",
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "skill_id": "desktop.system_task",
                "proposal_kind": proposal.get("kind"),
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status="accepted",
            response=response,
            agent="desktop-system-task-agent",
            flow="chat",
            audit_id=audit_id,
        )

    async def _handle_system_task_pending(
        self,
        payload: ChatRequest,
        audit_id: str,
        context_key: str,
    ) -> ChatResponse:
        pending_kind = self._system_task_agent.pending_kind(context_key)

        if pending_kind == "ask_user":
            # La respuesta es dato libre (no un si/no) — se pasa tal cual al bucle.
            result = await self._system_task_agent.confirm(context_key, payload.message)
            if result is None:
                response = "No había ninguna tarea pendiente."
            elif result.get("next_question"):
                response = result["next_question"]
            elif result.get("next_script"):
                response = (
                    f"Con eso ya puedo resolverlo ({result.get('next_description')}):\n"
                    f"```\n{result['next_script']}\n```\n¿Confirmas que lo ejecute?"
                )
            elif result.get("error"):
                response = f"No lo he conseguido: {result['error']}"
            else:
                response = result.get("content") or "Hecho."
        else:
            lowered = payload.message.strip().lower()
            if any(w in lowered for w in ("si", "sí", "confirmo", "adelante", "dale", "hazlo", "vale", "ok")):
                result = await self._system_task_agent.confirm(context_key)
                if result and result.get("error"):
                    response = f"No lo he conseguido: {result['error']}"
                elif result:
                    response = result.get("content") or "Hecho."
                else:
                    response = "No había ninguna tarea pendiente."
            elif any(w in lowered for w in ("no", "cancela", "cancelar", "olvidalo", "olvídalo", "déjalo", "dejalo")):
                self._system_task_agent.cancel(context_key)
                response = "Vale, no toco nada."
            else:
                response = "¿Confirmas que lo haga? (sí/no)"

        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status="accepted",
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "skill_id": "desktop.system_task",
                "pending_resolution": response[:200],
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status="accepted",
            response=response,
            agent="desktop-system-task-agent",
            flow="chat",
            audit_id=audit_id,
        )

    async def _handle_docker_prediagnostic_chat(
        self,
        payload: ChatRequest,
        resolution: dict[str, Any],
        audit_id: str,
    ) -> ChatResponse:
        container = resolution.get("entities", {}).get("container")
        report = await self._docker_diagnostics.run(container=container, alert_hint=payload.message)
        response = self._render_docker_prediagnostic_response(payload.message, report)
        status = "accepted"
        agent_name = "docker-prediagnostic"

        if self._llm_router is not None:
            llm_prompt = self._build_docker_llm_prompt(payload.message, report)
            result = await GenerationAgent(router=self._llm_router).ejecutar(
                llm_prompt,
                {"mode": payload.mode, "skill_id": resolution.get("skill_id"), "container": container},
                [],
            )
            if result.exito and result.respuesta:
                response = result.respuesta
                agent_name = result.agente or "GenerationAgent"
            else:
                status = "degraded"

        await self._audit(
            flow="chat",
            action="handle_chat",
            actor=payload.user_id,
            status=status,
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "skill_id": resolution.get("skill_id"),
                "container": container,
                "diagnostic_status": report.get("status"),
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status=status,
            response=response,
            agent=agent_name,
            flow="chat",
            audit_id=audit_id,
        )

    async def _handle_assets_ticket_chat(
        self,
        payload: ChatRequest,
        resolution: dict[str, Any],
        audit_id: str,
    ) -> ChatResponse:
        if self._operations is None:
            response = "La integracion de ticketing de Assets no esta disponible en este runtime."
            await self._audit(
                flow="chat",
                action="create_assets_ticket",
                actor=payload.user_id,
                status="degraded",
                details={
                    "mode": payload.mode,
                    "context_id": payload.context_id,
                    "message_preview": payload.message[:160],
                    "reason": "operations_service_missing",
                },
                audit_id=audit_id,
            )
            return ChatResponse(
                status="degraded",
                response=response,
                agent="operator-ticketing",
                flow="chat",
                audit_id=audit_id,
            )

        try:
            result = await self._operations.create_ticket_from_message(
                payload.message,
                source="codex",
                actor=payload.user_id,
                trigger_kind="operator",
                context={
                    "mode": payload.mode,
                    "context_id": payload.context_id,
                    "skill_entities": resolution.get("entities", {}),
                },
            )
            ticket_payload = result.get("ticket_payload", {})
            response = (
                f"He creado el ticket #{result.get('task_id')} en Assets: "
                f"{result.get('task_title') or ticket_payload.get('title', 'sin titulo')}.\n"
                f"Tipo: {ticket_payload.get('ticket_type', 'task')} · "
                f"Prioridad: {ticket_payload.get('priority', 'medium')} · "
                f"Estado: {ticket_payload.get('status', 'pending')}."
            )
            status = "accepted"
        except Exception as exc:
            response = f"No he podido crear el ticket en Assets: {exc}"
            status = "degraded"
            result = {
                "task_id": None,
                "task_title": None,
                "ticket_payload": {},
                "error": str(exc),
            }

        await self._audit(
            flow="chat",
            action="create_assets_ticket",
            actor=payload.user_id,
            status=status,
            details={
                "mode": payload.mode,
                "context_id": payload.context_id,
                "message_preview": payload.message[:160],
                "ticket_id": result.get("task_id"),
                "ticket_title": result.get("task_title"),
                "ticket_payload": result.get("ticket_payload", {}),
                "skill_id": resolution.get("skill_id"),
            },
            audit_id=audit_id,
        )
        return ChatResponse(
            status=status,
            response=response,
            agent="operator-ticketing",
            flow="chat",
            audit_id=audit_id,
        )

    async def handle_incident(self, payload: IncidentIngestRequest) -> IncidentResponse:
        runbook = self._resolve_runbook(payload)
        ticket = await self._maybe_create_ticket(payload, runbook)
        incident, response = await self._incident_pipeline.process(
            payload,
            runbook=runbook,
            ticket=ticket,
        )
        await self._incident_repository.upsert(incident)
        await self._audit(
            flow="incident",
            action="handle_incident",
            actor=payload.source,
            status=response.status,
            details={
                "incident_id": response.incident_id,
                "severity": response.severity,
                "next_action": response.next_action,
            },
        )
        return response

    async def list_incidents(self, limit: int = 50) -> IncidentListResponse:
        incidents = await self._incident_repository.list_recent(limit=limit)
        return IncidentListResponse(status="success", total=len(incidents), incidents=incidents)

    async def get_incident(self, incident_id: str) -> dict[str, object]:
        incident = await self._incident_repository.get(incident_id)
        if incident is None:
            return {"status": "not_found", "incident": None}
        return {"status": "success", "incident": incident}

    async def update_incident(
        self,
        incident_id: str,
        *,
        status: str,
        actor: str,
        owner: str | None = None,
        resolution_note: str | None = None,
    ) -> dict[str, object]:
        next_action = "resolved" if status == "resolved" else "manual_followup"
        updated = await self._incident_repository.update(
            incident_id,
            status=status,
            owner=owner,
            resolution_note=resolution_note,
            next_action=next_action,
        )
        if updated is None:
            return {"status": "not_found", "incident": None}
        await self._audit(
            flow="incident",
            action="update_incident",
            actor=actor,
            status="success",
            details={"incident_id": incident_id, "new_status": status, "owner": owner},
        )
        return {"status": "success", "incident": updated}

    async def execute_incident_action(
        self,
        incident_id: str,
        *,
        action_name: str,
        actor: str,
        dry_run: bool,
    ) -> dict[str, object]:
        incident = await self._incident_repository.get(incident_id)
        if incident is None:
            return {"status": "not_found", "incident": None}

        runbook = incident.get("runbook") or {}
        allowed_actions = runbook.get("auto_actions", [])
        if action_name not in allowed_actions:
            await self._audit(
                flow="incident",
                action="execute_incident_action",
                actor=actor,
                status="blocked",
                details={"incident_id": incident_id, "action_name": action_name, "reason": "not_allowed"},
            )
            return {
                "status": "blocked",
                "incident_id": incident_id,
                "action_name": action_name,
                "reason": "action_not_allowed_by_runbook",
            }

        if dry_run:
            result = {
                "status": "preview",
                "incident_id": incident_id,
                "action_name": action_name,
                "result": "dry_run_only",
            }
        else:
            execution = await self._executor.execute(
                ToolAction(
                    name=action_name,
                    target=incident.get("title", incident_id),
                    risk="medium" if incident.get("severity") == "critical" else "low",
                )
            )
            result = {
                "status": "executed",
                "incident_id": incident_id,
                "action_name": action_name,
                "result": execution,
            }

        await self._audit(
            flow="incident",
            action="execute_incident_action",
            actor=actor,
            status=result["status"],
            details={"incident_id": incident_id, "action_name": action_name, "dry_run": dry_run},
        )
        return result

    async def get_alerts(self) -> AlertsResponse:
        alerts = await self._alertmanager.fetch_alerts()
        enriched = [self._enrich_alert(alert) for alert in alerts]
        firing = sum(1 for alert in enriched if alert.get("status", {}).get("state") == "active")
        return AlertsResponse(
            status="success",
            total=len(enriched),
            firing=firing,
            alerts=enriched,
        )

    async def query_metrics(self, payload: PrometheusQueryRequest) -> PrometheusQueryResponse:
        result = await self._prometheus.instant_query(payload.query)
        return PrometheusQueryResponse(
            status="success",
            query=payload.query,
            result_count=len(result),
            result=result,
        )

    async def ingest_metrics(self, payload: MetricsIngestRequest) -> MetricsIngestResponse:
        await self._audit(
            flow="monitoring",
            action="ingest_metrics",
            actor=payload.source,
            status="accepted",
            details={"metrics_count": len(payload.metrics), "alerts_count": len(payload.alerts)},
        )
        return MetricsIngestResponse(
            status="accepted",
            source=payload.source,
            metrics_count=len(payload.metrics),
            alerts_count=len(payload.alerts),
        )

    async def silence_alert(self, payload: AlertSilenceRequest) -> AlertSilenceResponse:
        silence_id = await self._alertmanager.create_silence(
            alert_name=payload.alert_name,
            created_by=payload.created_by,
            duration_seconds=payload.duration_seconds,
            comment=payload.comment,
        )
        await self._audit(
            flow="monitoring",
            action="silence_alert",
            actor=payload.created_by,
            status="success",
            details={"alert_name": payload.alert_name, "silence_id": silence_id},
        )
        return AlertSilenceResponse(status="success", silence_id=silence_id)

    async def create_incident_from_alert(self, payload: IncidentIngestRequest) -> IncidentResponse:
        runbook = self._resolve_runbook(payload)
        ticket = await self._maybe_create_ticket(payload, runbook)
        incident, response = await self._alert_pipeline.open_incident(
            payload,
            runbook=runbook,
            ticket=ticket,
        )
        await self._incident_repository.upsert(incident)
        await self._audit(
            flow="monitoring",
            action="alert_to_incident",
            actor=payload.source,
            status=response.status,
            details={"incident_id": response.incident_id, "title": payload.title},
        )
        return response

    async def list_audit_entries(self, limit: int = 50) -> dict[str, object]:
        entries = await self._audit_repository.list_recent(limit=limit)
        return {"status": "success", "total": len(entries), "entries": entries}

    async def list_runbooks(self) -> RunbooksResponse:
        runbooks = self._runbooks.list_all()
        return RunbooksResponse(status="success", total=len(runbooks), runbooks=runbooks)

    async def get_collector_status(self) -> dict[str, object]:
        collectors: list[dict[str, object]] = []
        for name, kind, connector in (
            ("Prometheus", "collector", self._prometheus),
            ("Alertmanager", "alarm-routing", self._alertmanager),
            ("Grafana", "visualization", self._grafana),
        ):
            try:
                report = await connector.healthcheck()
                collectors.append(report)
            except Exception as exc:
                collectors.append(
                    {
                        "name": name,
                        "kind": kind,
                        "status": "down",
                        "endpoint": getattr(connector, "_base_url", ""),
                        "reason": str(exc),
                    }
                )

        overall = "up" if all(item["status"] == "up" for item in collectors) else "degraded"
        return {
            "status": "success",
            "overall": overall,
            "collectors": collectors,
        }

    async def handle_alertmanager_webhook(
        self,
        payload: AlertWebhookRequest,
    ) -> AlertWebhookResponse:
        incidents_created = 0
        incidents_resolved = 0

        for alert in payload.alerts:
            alert_status = alert.get("status", payload.status)
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            title = annotations.get("summary") or labels.get("alertname") or "alert-without-name"
            fingerprint = alert.get("fingerprint") or labels.get("fingerprint")

            if alert_status == "resolved":
                if fingerprint:
                    updated = await self._incident_repository.update(
                        fingerprint,
                        status="resolved",
                        next_action="resolved",
                        resolution_note="Resolved from Alertmanager webhook",
                    )
                    if updated is not None:
                        incidents_resolved += 1
                continue

            incident_payload = IncidentIngestRequest(
                source="alertmanager-webhook",
                title=title,
                severity=labels.get("severity", "warning"),
                fingerprint=fingerprint,
                payload={
                    "alert_name": labels.get("alertname"),
                    "labels": labels,
                    "annotations": annotations,
                    "starts_at": alert.get("startsAt"),
                    "ends_at": alert.get("endsAt"),
                    "generator_url": alert.get("generatorURL"),
                },
            )
            await self.create_incident_from_alert(incident_payload)
            incidents_created += 1

        await self._audit(
            flow="monitoring",
            action="alertmanager_webhook",
            actor=payload.receiver or "alertmanager",
            status="accepted",
            details={
                "received": len(payload.alerts),
                "incidents_created": incidents_created,
                "incidents_resolved": incidents_resolved,
                "group_key": payload.groupKey,
            },
        )
        return AlertWebhookResponse(
            status="accepted",
            received=len(payload.alerts),
            incidents_created=incidents_created,
            incidents_resolved=incidents_resolved,
        )

    def _resolve_runbook(self, payload: IncidentIngestRequest) -> dict:
        alert_name = payload.payload.get("alert_name") or payload.payload.get("alertname") or payload.title
        runbook = self._runbooks.get(alert_name)
        runbook["recommended_execution"] = "auto_allowed" if can_auto_execute(payload.severity) else "manual_gate"
        return runbook

    async def _maybe_create_ticket(self, payload: IncidentIngestRequest, runbook: dict) -> dict:
        if not should_create_ticket(payload.severity, runbook):
            return {}

        # Assets es el backend primario
        if self._operations is not None:
            try:
                return await self._operations.create_ticket_from_alarm(
                    title=payload.title,
                    severity=payload.severity,
                    details=payload.payload,
                    source="codex",
                )
            except Exception as exc:
                return {"status": "error", "provider": "assets", "reason": str(exc)}

        # Jira como backend alternativo
        if self._jira is not None:
            try:
                return await self._jira.create_incident_ticket(
                    title=payload.title,
                    severity=payload.severity,
                    details=payload.payload,
                )
            except Exception as exc:
                return {"status": "error", "provider": "jira", "reason": str(exc)}

        return {"status": "not_configured", "reason": "no_itsm_backend_available"}

    def _enrich_alert(self, alert: dict) -> dict:
        payload = dict(alert)
        labels = payload.get("labels", {})
        alert_name = labels.get("alertname", "unknown")
        payload["runbook"] = self._runbooks.get(alert_name)
        payload["recommended_execution"] = "manual_gate" if labels.get("severity") == "critical" else "diagnose_only"
        return payload

    def _build_docker_llm_prompt(self, user_message: str, report: dict[str, Any]) -> str:
        compact_report = json.dumps(report, ensure_ascii=False, indent=2)
        return (
            "Actúa como un operador de infraestructura senior. "
            "Te paso una alarma o petición del usuario y las evidencias recogidas de Docker. "
            "Haz un prediagnóstico breve y útil en español. No empieces pidiendo más información; "
            "si faltan datos, trabaja con hipótesis explícitas y di qué comprobarías después. "
            "Usa este formato:\n"
            "1. Qué parece estar pasando\n"
            "2. Evidencias observadas\n"
            "3. Siguiente comprobación recomendada\n"
            "4. Riesgo o impacto estimado\n\n"
            f"Petición original:\n{user_message}\n\n"
            f"Evidencias Docker:\n{compact_report}"
        )

    def _build_technology_llm_prompt(self, user_message: str, plan: dict[str, Any]) -> str:
        compact_plan = json.dumps(plan, ensure_ascii=False, indent=2)
        return (
            "Actúa como un operador de infraestructura senior. "
            "Te paso una petición del usuario y un plan de investigación inicial generado por Nexus. "
            "Devuelve un prediagnóstico breve y práctico en español. No empieces pidiendo más información; "
            "si faltan datos, formula hipótesis razonables y deja claro qué validarías después. "
            "Usa este formato:\n"
            "1. Qué dominio tecnológico parece afectado\n"
            "2. Qué hipótesis iniciales tienen más sentido\n"
            "3. Qué datos o comprobaciones faltan\n"
            "4. Siguiente paso recomendado\n"
            "5. Riesgo estimado\n\n"
            f"Petición original:\n{user_message}\n\n"
            f"Plan de investigación:\n{compact_plan}"
        )

    def _build_docker_llm_prompt(self, user_message: str, report: dict[str, Any]) -> str:
        compact_report = json.dumps(report, ensure_ascii=False, indent=2)
        return resolve_prompt_sync("nexus.docker_prediagnostic").format(
            user_message=user_message,
            context_json=compact_report,
        )

    def _build_technology_llm_prompt(self, user_message: str, plan: dict[str, Any]) -> str:
        compact_plan = json.dumps(plan, ensure_ascii=False, indent=2)
        return resolve_prompt_sync("nexus.technology_prediagnostic").format(
            user_message=user_message,
            context_json=compact_plan,
        )

    def _render_docker_prediagnostic_response(self, user_message: str, report: dict[str, Any]) -> str:
        observations = report.get("observations", [])
        lines = [
            "Pre diagnóstico Docker disponible.",
            report.get("summary", "Sin resumen disponible."),
        ]
        if observations:
            lines.append("Observaciones:")
            lines.extend(f"- {item}" for item in observations[:5])
        lines.append(f"Petición original: {user_message}")
        return "\n".join(lines)

    def _render_technology_plan(self, plan: dict[str, Any]) -> str:
        lines = [
            f"Pre diagnóstico inicial para {plan.get('title', plan.get('technology_key', 'tecnología desconocida'))}.",
            plan.get("summary", "Sin resumen disponible."),
            "Pasos iniciales recomendados:",
        ]
        lines.extend(f"- {step}" for step in plan.get("steps", [])[:5])
        return "\n".join(lines)

    async def _audit(
        self,
        *,
        flow: str,
        action: str,
        actor: str,
        status: str,
        details: dict,
        audit_id: str | None = None,
    ) -> None:
        await self._audit_repository.append(
            AuditEntry(
                audit_id=audit_id or f"audit-{uuid.uuid4().hex[:12]}",
                flow=flow,
                action=action,
                actor=actor,
                status=status,
                details=details,
            )
        )
