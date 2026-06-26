"""Execution policy for the shell agent."""

SHELL_ALLOWED_CONNECTORS = ["ssh", "runtime.desktop_bridge"]

SHELL_HIGH_RISK_SKILLS = {
    "ssh.run_privileged_command",
    "ssh.write_remote_file",
    "ssh.restart_service",
}
