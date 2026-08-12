"""Authentication and authorization dependencies for Nexus APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from desktop.config import DesktopSettings
from desktop.runtime.skill_router import DesktopSkillRouter
from desktop.storage.monitoring_integrations import (
    DesktopMonitoringIntegrationStore,
    resolve_monitoring_base_urls,
)
from nexus.audit.repository import MemoryAuditRepository, MongoAuditRepository
from nexus.audit.pending_approvals import MemoryPendingApprovalRepository
from nexus.application.services.agent_runtime_service import AgentRuntimeService
from nexus.application.services.assistant_runtime_core import AssistantRuntimeCore
from nexus.cmdb.source import FileCMDB
from nexus.vault.service import VaultService
from nexus.access.service import AgentAccessService
from nexus.connectors.itsm.jira import JiraConnector
from nexus.connectors.observability.alertmanager import AlertmanagerConnector
from nexus.connectors.observability.grafana import GrafanaConnector
from nexus.connectors.observability.prometheus import PrometheusConnector
from nexus.diagnostics.docker_pre_diagnostic import DockerPreDiagnosticService
from nexus.incidents.repository import MemoryIncidentRepository, MongoIncidentRepository
from nexus.monitoring.runbooks import RunbookRegistry
from nexus.orchestration.coordinator import NexusCoordinator
from nexus.operations import AssetsOperationsService
from nexus.outreach import OutreachManager
from nexus.crm import CRMBridgeService
from nexus.prospecting import ProspectingAgentService
from nexus.prospecting.campaign_agent import CampaignAgent
from nexus.prompts import PromptManager, set_default_prompt_manager
from nexus.mail import ThunderbirdMailManager
from nexus.teams import TeamsChatManager
from nexus.pepo import CaseLogStore
from agents.llm_router import get_router


@dataclass
class NexusRuntime:
    """Runtime container for the Nexus v1 services."""

    coordinator: NexusCoordinator
    assistant_core: AssistantRuntimeCore
    agent_runtime: AgentRuntimeService
    outreach: OutreachManager
    crm: CRMBridgeService
    operations: AssetsOperationsService
    prospecting: ProspectingAgentService
    campaign: CampaignAgent
    prompts: PromptManager
    pending_approvals: MemoryPendingApprovalRepository = None
    cmdb:              FileCMDB = None
    vault:             VaultService = None
    access:            AgentAccessService = None
    agent_settings:    Any = None
    mail:              ThunderbirdMailManager = None
    teams:             TeamsChatManager = None
    case_log:          CaseLogStore = None
    jira:              JiraConnector = None


def build_runtime(cfg) -> NexusRuntime:
    """Build the default Nexus v1 runtime graph."""
    prompt_manager = PromptManager(getattr(cfg, "prompt_data_dir", "data/prompts"))
    set_default_prompt_manager(prompt_manager)
    llm_router = get_router()
    cmdb = FileCMDB()
    # vault/access se construyen aqui (no mas abajo, donde estaban antes) porque
    # NexusCoordinator los necesita para remote_ops_agent — el resto del runtime
    # los recibe igual via NexusRuntime.vault/.access mas abajo, sin cambios.
    vault = VaultService()
    access = AgentAccessService(cmdb=cmdb, vault=vault)
    monitoring_store = None
    mouse_agent = None
    system_task_agent = None
    remote_ops_agent = None
    self_config_agent = None
    skill_router = DesktopSkillRouter()
    agent_settings: "AgentSettingsStore | None" = None
    if getattr(cfg, "is_desktop", False):
        desktop_settings = DesktopSettings.from_env()
        monitoring_store = DesktopMonitoringIntegrationStore(
            desktop_settings.monitoring_config_db_path
        )
        from desktop.local_agents.mouse_agent import MouseAgent
        from desktop.local_agents.remote_ops_agent import RemoteOpsAgent
        from desktop.local_agents.self_config_agent import SelfConfigAgent
        from desktop.local_agents.skill_library import SkillLibrary
        from desktop.local_agents.system_task_agent import SystemTaskAgent
        from desktop.runtime.agent_settings import AgentSettingsStore
        from desktop.storage.local_state import DesktopLocalState

        mouse_agent = MouseAgent()
        skill_library = SkillLibrary(desktop_settings.skill_library_db_path)
        system_task_agent = SystemTaskAgent(cfg, llm_router=llm_router, skill_library=skill_library, cmdb=cmdb)
        remote_ops_agent = RemoteOpsAgent(cfg, llm_router=llm_router, cmdb=cmdb, vault=vault, access=access)
        desktop_local_state = DesktopLocalState(desktop_settings)
        self_config_agent = SelfConfigAgent(cfg, llm_router=llm_router, cmdb=cmdb, vault=vault, local_state=desktop_local_state)
        agent_settings = AgentSettingsStore(desktop_settings.config_dir / "agent_settings.json")
        # Un unico DesktopSkillRouter (con el override de permisos ya cargado)
        # compartido entre NexusCoordinator y AssistantRuntimeCore — antes cada
        # uno creaba el suyo por separado, sin overrides posibles.
        skill_router = DesktopSkillRouter(settings_store=agent_settings)
    monitoring_urls = resolve_monitoring_base_urls(cfg, monitoring_store)
    alertmanager = AlertmanagerConnector(
        monitoring_urls["alertmanager"],
        timeout_seconds=cfg.connector_timeout_seconds,
    )
    grafana = GrafanaConnector(
        monitoring_urls["grafana"],
        timeout_seconds=cfg.connector_timeout_seconds,
    )
    prometheus = PrometheusConnector(
        monitoring_urls["prometheus"],
        timeout_seconds=cfg.connector_timeout_seconds,
    )
    operations = AssetsOperationsService(cfg=cfg, llm_router=llm_router)
    jira_connector = JiraConnector(cfg)
    prospecting = ProspectingAgentService(cfg=cfg)
    coordinator = NexusCoordinator(
        alertmanager=alertmanager,
        grafana=grafana,
        prometheus=prometheus,
        operations=operations,
        jira=jira_connector,
        prospecting=prospecting,
        mouse_agent=mouse_agent,
        system_task_agent=system_task_agent,
        remote_ops_agent=remote_ops_agent,
        self_config_agent=self_config_agent,
        skill_router=skill_router,
        incident_repository=MemoryIncidentRepository(),
        audit_repository=MemoryAuditRepository(),
        runbooks=RunbookRegistry(),
        llm_router=llm_router,
        docker_diagnostics=DockerPreDiagnosticService(),
    )
    assistant_core = AssistantRuntimeCore(coordinator, llm_router=llm_router, skill_router=skill_router)
    agent_runtime = AgentRuntimeService()
    outreach = OutreachManager(cfg=cfg, llm_router=llm_router)
    crm = CRMBridgeService(cfg=cfg)
    campaign = CampaignAgent(prospecting_svc=prospecting, outreach_mgr=outreach, crm_svc=crm)
    case_log = CaseLogStore()
    mail = ThunderbirdMailManager(cfg=cfg, llm_router=llm_router)
    teams = TeamsChatManager(cfg=cfg, llm_router=llm_router, case_log=case_log)

    return NexusRuntime(
        coordinator=coordinator,
        assistant_core=assistant_core,
        agent_runtime=agent_runtime,
        outreach=outreach,
        crm=crm,
        operations=operations,
        prospecting=prospecting,
        campaign=campaign,
        prompts=prompt_manager,
        pending_approvals=MemoryPendingApprovalRepository(),
        cmdb=cmdb,
        vault=vault,
        access=access,
        agent_settings=agent_settings,
        mail=mail,
        teams=teams,
        case_log=case_log,
        jira=jira_connector,
    )


def upgrade_runtime_with_app_state(app, cfg) -> None:
    """Replace volatile repositories with Mongo-backed ones when collections exist."""
    runtime = getattr(app.state, "nexus_runtime", None)
    conversations = getattr(app.state, "conversations", None)
    if runtime is None or conversations is None:
        return

    database = conversations.database
    runtime.coordinator.use_persistence(
        incident_repository=MongoIncidentRepository(database.incidents),
        audit_repository=MongoAuditRepository(database.nexus_audit),
    )


def get_runtime(request: Request) -> NexusRuntime:
    """Fetch the Nexus runtime from FastAPI application state."""
    return request.app.state.nexus_runtime


def get_coordinator(request: Request) -> NexusCoordinator:
    """Fetch the Nexus coordinator from FastAPI application state."""
    return get_runtime(request).coordinator


def get_assistant_core(request: Request) -> AssistantRuntimeCore:
    """Fetch the shared assistant execution core from FastAPI application state."""
    runtime = get_runtime(request)
    assistant_core = getattr(runtime, "assistant_core", None)
    if assistant_core is not None:
        return assistant_core
    return AssistantRuntimeCore(runtime.coordinator)


def get_agent_runtime(request: Request) -> AgentRuntimeService:
    """Fetch the shared agent runtime used by desktop and web."""
    runtime = get_runtime(request)
    agent_runtime = getattr(runtime, "agent_runtime", None)
    if agent_runtime is not None:
        return agent_runtime
    return AgentRuntimeService()


def get_outreach_manager(request: Request) -> OutreachManager:
    """Fetch the outreach manager from FastAPI application state."""
    return get_runtime(request).outreach


def get_crm_manager(request: Request) -> CRMBridgeService:
    """Fetch the Assets CRM bridge from FastAPI application state."""
    return get_runtime(request).crm


def get_operations_manager(request: Request) -> AssetsOperationsService:
    """Fetch the Assets operations bridge from FastAPI application state."""
    return get_runtime(request).operations


def get_prompt_manager(request: Request) -> PromptManager:
    """Fetch the Nexus prompt manager from FastAPI application state."""
    return get_runtime(request).prompts


def get_prospecting_manager(request: Request) -> ProspectingAgentService:
    """Fetch the prospecting manager from FastAPI application state."""
    return get_runtime(request).prospecting


def get_campaign_agent(request: Request) -> CampaignAgent:
    """Fetch the campaign agent from FastAPI application state."""
    return get_runtime(request).campaign


def get_agent_settings_store(request: Request) -> Any:
    """Fetch the AgentSettingsStore (permission/enabled overrides) from application state."""
    return get_runtime(request).agent_settings


def get_pending_approvals(request: Request) -> MemoryPendingApprovalRepository:
    """Fetch the human-in-the-loop approval repository from FastAPI application state."""
    return get_runtime(request).pending_approvals


def get_cmdb(request: Request) -> FileCMDB:
    """Fetch the CMDB source from FastAPI application state."""
    return get_runtime(request).cmdb


def get_vault(request: Request) -> VaultService:
    """Fetch the credential vault from FastAPI application state."""
    return get_runtime(request).vault


def get_access_service(request: Request) -> AgentAccessService:
    """Fetch the AgentAccessService from FastAPI application state."""
    return get_runtime(request).access


def get_mail_manager(request: Request) -> ThunderbirdMailManager:
    """Fetch the Thunderbird mail manager from FastAPI application state."""
    return get_runtime(request).mail


def get_teams_manager(request: Request) -> TeamsChatManager:
    """Fetch the Teams chat manager from FastAPI application state."""
    return get_runtime(request).teams


def get_case_log_store(request: Request) -> CaseLogStore:
    """Fetch the PEPO per-case log store from FastAPI application state."""
    return get_runtime(request).case_log
