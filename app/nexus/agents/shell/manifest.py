"""Manifest for the shell agent."""

from nexus.agents.shared.result import AgentCapability, AgentManifest
from nexus.agents.shell.execution_policy import SHELL_ALLOWED_CONNECTORS

SHELL_MANIFEST = AgentManifest(
    agent_id="shell",
    name="Nexus Shell",
    role="shell",
    description="Ejecuta acciones en hosts, recoge evidencias y devuelve resultado estructurado.",
    accepted_modes=["shell", "execution", "investigation"],
    capabilities=[
        AgentCapability(
            capability_id="host.collect",
            name="Recogida remota",
            description="Lanza comandos controlados y recopila evidencias del sistema remoto.",
        ),
        AgentCapability(
            capability_id="host.act",
            name="Accion remota",
            description="Ejecuta cambios aprobados con politica y trazabilidad.",
        ),
    ],
    skill_ids=[
        "ssh.run_command",
        "ssh.collect_logs",
        "ssh.transfer_file",
    ],
    connector_ids=SHELL_ALLOWED_CONNECTORS,
    tags=["always-on", "remote-execution", "approval-aware"],
)
