"""Docker evidence collection for Nexus pre-diagnostics."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DockerCommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


class DockerPreDiagnosticService:
    """Collect read-only Docker evidence before the LLM reasons about it."""

    def __init__(self, docker_bin: str = "docker", timeout_seconds: int = 8) -> None:
        self._docker_bin = docker_bin
        self._timeout_seconds = timeout_seconds

    async def run(self, *, container: str | None, alert_hint: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._run_sync, container=container, alert_hint=alert_hint)

    def _run_sync(self, *, container: str | None, alert_hint: str | None = None) -> dict[str, Any]:
        version = self._docker_version()
        if not version["available"]:
            return {
                "status": "unavailable",
                "technology": "docker",
                "container": container,
                "alert_hint": alert_hint,
                "summary": "Docker no esta disponible desde este puesto o el CLI no responde.",
                "observations": [version["reason"]],
                "evidence": {},
            }

        containers = self._list_containers()
        target = self._resolve_target(container, containers)
        if target is None:
            return {
                "status": "no_target",
                "technology": "docker",
                "container": container,
                "alert_hint": alert_hint,
                "summary": "No he podido identificar un contenedor concreto; conviene revisar la alarma y el inventario.",
                "observations": [
                    f"Docker operativo: {version['version']}",
                    f"Contenedores visibles: {len(containers)}",
                ],
                "evidence": {
                    "docker_version": version["version"],
                    "containers": containers[:10],
                },
            }

        inspect_payload = self._inspect_container(target["Names"])
        stats_payload = self._container_stats(target["Names"])
        logs_excerpt = self._container_logs(target["Names"])
        observations = self._build_observations(
            target=target,
            inspect_payload=inspect_payload,
            stats_payload=stats_payload,
            logs_excerpt=logs_excerpt,
        )
        return {
            "status": "success",
            "technology": "docker",
            "container": target["Names"],
            "alert_hint": alert_hint,
            "summary": self._build_summary(target, inspect_payload, observations),
            "observations": observations,
            "evidence": {
                "docker_version": version["version"],
                "container_row": target,
                "inspect": inspect_payload,
                "stats": stats_payload,
                "logs_excerpt": logs_excerpt,
                "visible_containers": containers[:10],
            },
        }

    def _docker_version(self) -> dict[str, Any]:
        result = self._run_command([self._docker_bin, "version", "--format", "{{.Server.Version}}"])
        if not result.ok:
            return {"available": False, "reason": result.stderr or result.stdout or "docker version failed"}
        return {"available": True, "version": result.stdout.strip()}

    def _list_containers(self) -> list[dict[str, str]]:
        result = self._run_command([self._docker_bin, "ps", "-a", "--format", "{{json .}}"])
        if not result.ok:
            return []
        rows: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _inspect_container(self, container: str) -> dict[str, Any]:
        result = self._run_command([self._docker_bin, "inspect", container])
        if not result.ok:
            return {"available": False, "error": result.stderr or result.stdout}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"available": False, "error": "inspect_json_invalid"}
        return payload[0] if payload else {"available": False, "error": "inspect_empty"}

    def _container_stats(self, container: str) -> dict[str, Any]:
        result = self._run_command([self._docker_bin, "stats", "--no-stream", "--format", "{{json .}}", container])
        if not result.ok:
            return {"available": False, "error": result.stderr or result.stdout}
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {"available": False, "error": "stats_json_invalid"}

    def _container_logs(self, container: str, tail: int = 60) -> str:
        result = self._run_command([self._docker_bin, "logs", "--tail", str(tail), container])
        if not result.ok and not result.stdout:
            return result.stderr.strip()
        content = result.stdout.strip() or result.stderr.strip()
        return content[:4000]

    def _resolve_target(self, container: str | None, containers: list[dict[str, str]]) -> dict[str, str] | None:
        if not containers:
            return None
        if container:
            lowered = container.lower()
            for row in containers:
                names = str(row.get("Names", "")).lower()
                identifier = str(row.get("ID", "")).lower()
                if lowered == names or identifier.startswith(lowered) or lowered in names:
                    return row
        for row in containers:
            status = str(row.get("Status", "")).lower()
            if any(token in status for token in ("exited", "restarting", "unhealthy", "dead")):
                return row
        return containers[0]

    def _build_observations(
        self,
        *,
        target: dict[str, str],
        inspect_payload: dict[str, Any],
        stats_payload: dict[str, Any],
        logs_excerpt: str,
    ) -> list[str]:
        observations: list[str] = []
        state = inspect_payload.get("State", {})
        if state:
            observations.append(
                f"Estado Docker: status={state.get('Status')} running={state.get('Running')} restart_count={state.get('RestartCount', 0)}"
            )
            if state.get("OOMKilled"):
                observations.append("El contenedor ha sido terminado por OOMKilled.")
            if state.get("Error"):
                observations.append(f"Error reportado por Docker: {state.get('Error')}")
            health = state.get("Health", {})
            if health:
                observations.append(f"Healthcheck: {health.get('Status', 'unknown')}")
        if stats_payload.get("available", True) is not False:
            cpu = stats_payload.get("CPUPerc")
            mem = stats_payload.get("MemUsage")
            if cpu or mem:
                observations.append(f"Uso actual: CPU={cpu or 'n/a'} MEM={mem or 'n/a'}")
        status_text = str(target.get("Status", "")).strip()
        if status_text:
            observations.append(f"Resumen docker ps: {status_text}")
        if logs_excerpt:
            lowered_logs = logs_excerpt.lower()
            if "error" in lowered_logs or "exception" in lowered_logs or "fatal" in lowered_logs:
                observations.append("Los logs recientes contienen errores o excepciones.")
        return observations

    def _build_summary(self, target: dict[str, str], inspect_payload: dict[str, Any], observations: list[str]) -> str:
        state = inspect_payload.get("State", {})
        status = state.get("Status") or target.get("State") or "unknown"
        name = target.get("Names", "unknown")
        headline = f"Contenedor {name} detectado con estado {status}."
        if observations:
            return f"{headline} Observaciones iniciales: {' | '.join(observations[:3])}"
        return headline

    def _run_command(self, command: list[str]) -> DockerCommandResult:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return DockerCommandResult(False, "", "docker_cli_not_found", 127)
        except subprocess.TimeoutExpired:
            return DockerCommandResult(False, "", "docker_command_timeout", 124)
        return DockerCommandResult(
            ok=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
