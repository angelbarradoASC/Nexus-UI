"""
desktop/local_agents/manifest.py
------------------------------------
Manifest estatico para PEPO — el agente personal de escritorio — para que el
catalogo unificado (GET /api/nexus/agents/catalog) lo incluya junto a los 4
agentes formales (Supervisor/Operator/Shell/Sales) sin forzar un cambio de
diseño en cada modulo interno.

Importante: SystemTaskAgent, RemoteOpsAgent, MouseAgent y
DockerPreDiagnosticService NO son agentes en si mismos — son las skills/
herramientas que PEPO usa (razona con un bucle de tool-calling y decide cual
invocar). Antes cada una tenia su propia tarjeta en el catalogo, lo cual
mezclaba "agente" con "tarea que un agente ejecuta". Un unico manifest PEPO
agrupa todos sus skill_ids.

CampaignAgent SI aparece aqui (agent_id="campaign"): es un agente real (una
de las 5 columnas fijas del catalogo — PEPO, Campaña, Sales, Operator,
Shell), aunque no se invoque via skill_id/chat sino por el scheduler o la
propia pestaña Campaña.
"""

from __future__ import annotations

from nexus.agents.shared.result import AgentCapability, AgentManifest

LOCAL_AGENT_MANIFESTS: list[AgentManifest] = [
    AgentManifest(
        agent_id="pepo",
        name="PEPO",
        role="personal_assistant",
        description="Agente personal de escritorio — razona con un bucle de tool-calling propio (CMDB, Vault, SSH, PowerShell local) y actúa solo tras confirmación humana en lo que toca algo real.",
        supported_surfaces=["desktop"],
        accepted_modes=["operator", "monitoring", "incident", "general"],
        capabilities=[
            AgentCapability(capability_id="cmdb.lookup", name="Consulta CMDB", description="Busca datos conocidos en el inventario antes de suponerlos o preguntar."),
            AgentCapability(capability_id="local.run_script", name="Tarea en el PC local", description="Propone un script PowerShell sobre este ordenador, pendiente de confirmación."),
            AgentCapability(capability_id="mouse.adjust_speed", name="Ajustar ratón", description="Sube, baja, maximiza, minimiza o resetea la velocidad del puntero de este ordenador."),
            AgentCapability(capability_id="vault.check_credentials", name="Comprobar credenciales", description="Verifica si hay credenciales en el Vault para un dispositivo, sin revelar el secreto."),
            AgentCapability(capability_id="ssh.run_diagnostic", name="Diagnóstico SSH remoto", description="Ejecuta un whitelist de comandos de solo lectura sobre un servidor del CMDB, pendiente de confirmación."),
            AgentCapability(capability_id="docker.inspect", name="Inspeccionar Docker", description="docker ps/inspect/stats/logs sobre el contenedor detectado o el más problemático, solo lectura."),
            AgentCapability(capability_id="vault.add_credential", name="Añadir credenciales al Vault", description="Da de alta un dispositivo (si es nuevo) y guarda sus credenciales cifradas en el Vault, pendiente de confirmación."),
            AgentCapability(capability_id="crm.configure", name="Configurar conexión a CRM", description="Configura la conexión de Sales a Assets CRM u Odoo, pendiente de confirmación."),
        ],
        skill_ids=[
            "desktop.system_task",
            "desktop.mouse_speed",
            "ssh.diagnostico",
            "linux.prediagnostico",
            "windows.prediagnostico",
            "docker.prediagnostico",
            "vault.add_credential",
            "crm.configurar",
        ],
        connector_ids=["cmdb", "vault", "ssh", "powershell", "docker_cli", "windows_registry", "crm"],
        tags=["pepo", "local", "confirmable"],
    ),
    AgentManifest(
        agent_id="campaign",
        name="Campaña de prospección",
        role="commercial",
        description="Ciclo diario de prospección B2B (descubrimiento, auditoría, propuesta, contacto) — no se invoca por chat, lo dispara el scheduler o la pestaña Campaña.",
        supported_surfaces=["desktop"],
        accepted_modes=["sales", "prospecting"],
        capabilities=[
            AgentCapability(capability_id="campaign.run_daily", name="Ciclo diario", description="Follow-ups + nuevos prospectos + contacto, dentro del límite diario configurado."),
        ],
        skill_ids=[],
        connector_ids=["cmdb", "crm", "smtp"],
        tags=["scheduled", "commercial"],
    ),
]
