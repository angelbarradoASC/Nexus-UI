"""Assets Consultores ticketing helpers for Operator."""

from __future__ import annotations

import json
from typing import Any

import httpx

from agents.generation_agent import GenerationAgent
from agents.utils.llm_parser import clean_llm_response
from nexus.connectors.crm import AssetsCRMConnector
from nexus.prompts import resolve_prompt_sync
from nexus.utils.llm_json import strip_llm_fences


class AssetsOperationsService:
    """Expose a compact ticketing surface backed by the Assets private API."""

    def __init__(
        self,
        *,
        cfg,
        connector: AssetsCRMConnector | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self._cfg = cfg
        self._llm_router = llm_router
        self._connector = connector or AssetsCRMConnector(
            base_url=cfg.assets_crm_base_url,
            username=cfg.assets_crm_username,
            password=cfg.assets_crm_password,
            timeout_seconds=cfg.connector_timeout_seconds,
        )

    async def status(self) -> dict[str, Any]:
        connector_status = await self._connector.status()
        return {
            "status": connector_status.get("status", "down"),
            "provider": "assets-web-api",
            "connector": connector_status,
        }

    async def bootstrap(self) -> dict[str, Any]:
        connector_status = await self._connector.status()
        if connector_status.get("status") != "up":
            return {
                "status": "down",
                "provider": "assets-web-api",
                "connector": connector_status,
                "companies": [],
                "projects": [],
                "users": [],
                "can_assign": False,
                "users_error": connector_status.get("error"),
            }

        companies_payload = await self._connector.list_companies()
        projects_payload = await self._connector.list_projects()

        users: list[dict[str, Any]] = []
        can_assign = False
        users_error: str | None = None

        try:
            users_payload = await self._connector.list_users()
            users = list(users_payload.get("users", []))
            can_assign = bool(users)
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                users_error = "El usuario tecnico actual no puede listar usuarios asignables."
            else:
                raise
        except Exception as exc:  # pragma: no cover - remote failure variance
            users_error = str(exc)

        return {
            "status": "up",
            "provider": "assets-web-api",
            "connector": connector_status,
            "companies": list(companies_payload.get("companies", [])),
            "projects": list(projects_payload.get("projects", [])),
            "users": users,
            "can_assign": can_assign,
            "users_error": users_error,
        }

    async def list_tickets(self) -> dict[str, Any]:
        payload = await self._connector.list_tasks()
        tasks = list(payload.get("tasks", []))
        tasks.sort(
            key=lambda task: (
                str(task.get("updated_at") or task.get("created_at") or ""),
                int(task.get("id") or 0),
            ),
            reverse=True,
        )
        return {
            "status": "ok",
            "tasks": tasks,
            "total": len(tasks),
        }

    async def create_ticket(self, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._clean_ticket_payload(payload, allow_partial=False)
        return await self._connector.create_task(cleaned)

    async def update_ticket(self, task_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._clean_ticket_payload(payload, allow_partial=True)
        return await self._connector.update_task(task_id, cleaned)

    async def delete_ticket(self, task_id: int) -> dict[str, Any]:
        return await self._connector.delete_task(task_id)

    async def create_ticket_from_message(
        self,
        message: str,
        *,
        source: str = "codex",
        actor: str = "operator",
        trigger_kind: str = "operator",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enriched = await self.enrich_ticket_from_message(
            message,
            source=source,
            trigger_kind=trigger_kind,
            context=context,
        )
        created = await self.create_ticket(enriched["ticket_payload"])
        task = created.get("task", {})
        return {
            "status": "created",
            "actor": actor,
            "trigger_kind": trigger_kind,
            "message": message,
            "ticket_payload": enriched["ticket_payload"],
            "extracted": enriched["extracted"],
            "result": created,
            "task_id": task.get("id"),
            "task_title": task.get("title"),
        }

    async def enrich_ticket_from_message(
        self,
        message: str,
        *,
        source: str = "codex",
        trigger_kind: str = "operator",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bootstrap = await self.bootstrap()
        companies = list(bootstrap.get("companies", []))
        projects = list(bootstrap.get("projects", []))
        users = list(bootstrap.get("users", []))
        context = context or {}

        extracted = await self._extract_ticket_data_with_llm(
            message,
            trigger_kind=trigger_kind,
            context=context,
        )
        if not extracted:
            extracted = self._extract_ticket_data_fallback(
                message,
                trigger_kind=trigger_kind,
                context=context,
            )

        company = self._resolve_reference(
            extracted.get("company_hint"),
            companies,
            label_fields=("name", "domain"),
        )
        project = self._resolve_reference(
            extracted.get("project_hint"),
            projects,
            label_fields=("name", "code", "project_code"),
        )
        assignee = self._resolve_reference(
            extracted.get("assigned_to_hint"),
            users,
            label_fields=("username", "realName", "name"),
        )

        description = self._build_ticket_description(
            message,
            extracted=extracted,
            context=context,
            trigger_kind=trigger_kind,
        )

        payload = {
            "title": extracted.get("title") or self._fallback_title(message, trigger_kind=trigger_kind),
            "ticket_type": extracted.get("ticket_type") or ("incident" if trigger_kind == "alarm" else "task"),
            "status": extracted.get("status") or "pending",
            "priority": extracted.get("priority") or self._infer_priority(message, context=context),
            "due_date": extracted.get("due_date") or "",
            "company_id": company.get("id") if company else None,
            "project_id": project.get("id") if project else None,
            "assigned_to_id": assignee.get("id") if assignee else None,
            "source": source or extracted.get("source") or "manual",
            "description": description,
        }

        return {
            "status": "ok",
            "trigger_kind": trigger_kind,
            "ticket_payload": self._clean_ticket_payload(payload, allow_partial=False),
            "extracted": extracted,
            "resolved": {
                "company": company,
                "project": project,
                "assignee": assignee,
            },
        }

    async def create_ticket_from_alarm(
        self,
        *,
        title: str,
        severity: str,
        details: dict[str, Any],
        source: str = "codex",
    ) -> dict[str, Any]:
        message = f"{title}. Severidad: {severity}."
        return await self.create_ticket_from_message(
            message,
            source=source,
            actor="alertmanager",
            trigger_kind="alarm",
            context={"severity": severity, "details": details},
        )

    async def _extract_ticket_data_with_llm(
        self,
        message: str,
        *,
        trigger_kind: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self._llm_router is None:
            return {}

        prompt = resolve_prompt_sync("nexus.assets_ticket_extract").format(
            trigger_kind=trigger_kind,
            user_message=message,
            context_json=json.dumps(context, ensure_ascii=False, indent=2),
        )
        result = await GenerationAgent(router=self._llm_router).ejecutar(
            prompt,
            {"trigger_kind": trigger_kind},
            [],
        )
        if not result.exito or not result.respuesta:
            return {}

        raw = strip_llm_fences(clean_llm_response(result.respuesta))
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _extract_ticket_data_fallback(
        self,
        message: str,
        *,
        trigger_kind: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        lowered = message.lower()
        return {
            "title": self._fallback_title(message, trigger_kind=trigger_kind),
            "ticket_type": "incident" if trigger_kind == "alarm" or any(term in lowered for term in ("alarma", "alerta", "caido", "caída", "caida", "falla", "error")) else "task",
            "priority": self._infer_priority(message, context=context),
            "status": "pending",
            "source": "codex",
            "company_hint": "",
            "project_hint": "",
            "assigned_to_hint": "",
            "description_summary": message.strip(),
            "impact": context.get("severity") or "",
            "due_date": "",
        }

    def _build_ticket_description(
        self,
        message: str,
        *,
        extracted: dict[str, Any],
        context: dict[str, Any],
        trigger_kind: str,
    ) -> str:
        lines = [
            f"Origen: {trigger_kind}",
            f"Mensaje original: {message.strip()}",
        ]
        if extracted.get("description_summary"):
            lines.append(f"Resumen IA: {extracted['description_summary']}")
        if extracted.get("impact"):
            lines.append(f"Impacto: {extracted['impact']}")
        if extracted.get("next_step"):
            lines.append(f"Siguiente paso sugerido: {extracted['next_step']}")
        if extracted.get("affected_service"):
            lines.append(f"Servicio afectado: {extracted['affected_service']}")
        if context:
            lines.append("Contexto estructurado:")
            lines.append(json.dumps(context, ensure_ascii=False, indent=2))
        return "\n".join(line for line in lines if line)

    def _resolve_reference(
        self,
        hint: str | None,
        items: list[dict[str, Any]],
        *,
        label_fields: tuple[str, ...],
    ) -> dict[str, Any] | None:
        normalized_hint = self._normalize_hint(hint)
        if not normalized_hint:
            return None

        exact_match = next(
            (
                item
                for item in items
                if any(self._normalize_hint(item.get(field)) == normalized_hint for field in label_fields)
            ),
            None,
        )
        if exact_match is not None:
            return exact_match

        contains_match = next(
            (
                item
                for item in items
                if any(normalized_hint in self._normalize_hint(item.get(field)) for field in label_fields)
            ),
            None,
        )
        return contains_match

    @staticmethod
    def _normalize_hint(value: Any) -> str:
        return " ".join(str(value or "").lower().strip().replace("-", " ").replace("_", " ").split())

    @staticmethod
    def _fallback_title(message: str, *, trigger_kind: str) -> str:
        cleaned = " ".join(message.strip().split())
        if not cleaned:
            return "Ticket operativo sin resumen"
        first_sentence = cleaned.split(".", 1)[0].split(":", 1)[-1].strip()
        title = first_sentence[:120].strip() or cleaned[:120].strip()
        prefix = "Alarma" if trigger_kind == "alarm" else "Operador"
        return title if len(title) > 12 else f"{prefix}: {title}"

    @staticmethod
    def _infer_priority(message: str, *, context: dict[str, Any]) -> str:
        lowered = message.lower()
        severity = str(context.get("severity") or "").lower()
        if severity in {"critical", "critico", "critica"}:
            return "high"
        if any(term in lowered for term in ("critico", "crítico", "urgente", "produccion", "producción", "caido", "caída", "caida", "down", "no responde")):
            return "high"
        if any(term in lowered for term in ("degradado", "degradada", "lento", "latencia", "warning")):
            return "medium"
        return "medium"

    def _clean_ticket_payload(
        self,
        payload: dict[str, Any],
        *,
        allow_partial: bool,
    ) -> dict[str, Any]:
        normalized = {
            "title": str(payload.get("title") or "").strip(),
            "ticket_type": str(payload.get("ticket_type") or "task").strip() or "task",
            "status": str(payload.get("status") or "pending").strip() or "pending",
            "priority": str(payload.get("priority") or "medium").strip() or "medium",
            "due_date": str(payload.get("due_date") or "").strip(),
            "company_id": payload.get("company_id"),
            "project_id": payload.get("project_id"),
            "assigned_to_id": payload.get("assigned_to_id"),
            "source": str(payload.get("source") or "manual").strip() or "manual",
            "description": str(payload.get("description") or "").strip(),
        }

        if not allow_partial and not normalized["title"]:
            raise ValueError("El ticket necesita un titulo")

        cleaned: dict[str, Any] = {}
        for key, value in normalized.items():
            if key in {"company_id", "project_id", "assigned_to_id"}:
                if value in (None, "", 0, "0"):
                    cleaned[key] = None
                else:
                    cleaned[key] = int(value)
                continue
            if value == "" and key not in {"description", "due_date"}:
                if allow_partial:
                    continue
            cleaned[key] = value

        if allow_partial:
            cleaned = {
                key: value
                for key, value in cleaned.items()
                if value is not None or key in {"company_id", "project_id", "assigned_to_id"}
            }
        return cleaned
