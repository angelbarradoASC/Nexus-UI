"""Interactive shell for Open-Nexus."""

from __future__ import annotations

import asyncio
from typing import Any

from desktop.opennexus.engine import OpenNexusEngine

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # pragma: no cover - graceful fallback when rich is absent
    Console = None
    Panel = None
    Table = None


class OpenNexusShell:
    """Terminal-first operator shell inspired by Open Interpreter."""

    def __init__(self, engine: OpenNexusEngine | None = None) -> None:
        self.engine = engine or OpenNexusEngine()
        self.console = Console() if Console else None

    def run(self) -> None:
        """Start the interactive shell loop."""
        self._render_banner()
        while True:
            try:
                user_input = input("open-nexus> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._write("\nCierro Open-Nexus.")
                break

            if not user_input:
                continue
            if user_input in {"/quit", "/exit"}:
                self._write("Cierro Open-Nexus.")
                break
            if user_input == "/help":
                self._render_help()
                continue
            if user_input == "/runtime":
                self._render_runtime()
                continue
            if user_input == "/paths":
                self._render_paths()
                continue
            if user_input == "/skills":
                self._render_skills()
                continue
            if user_input == "/history":
                self._render_history()
                continue

            result = asyncio.run(self.engine.execute(user_input))
            self._render_result(result.to_dict())

    def _render_banner(self) -> None:
        text = (
            "Open-Nexus\n"
            "Shell local inspirado en Open Interpreter.\n"
            "Usa /help, /runtime, /paths, /skills, /history o /quit."
        )
        if self.console and Panel:
            self.console.print(Panel.fit(text, border_style="green"))
        else:
            print(text)

    def _render_help(self) -> None:
        help_text = (
            "/help     muestra esta ayuda\n"
            "/runtime  ensena el runtime local y capacidades\n"
            "/paths    ensena las rutas locales de Open-Nexus\n"
            "/skills   lista skills detectables\n"
            "/history  ensena las ultimas interacciones\n"
            "/quit     salir"
        )
        self._write(help_text)

    def _render_runtime(self) -> None:
        snapshot = self.engine.snapshot()
        if self.console and Table:
            table = Table(title="Runtime local")
            table.add_column("Campo")
            table.add_column("Valor", overflow="fold")
            table.add_row("Producto", snapshot["product"]["name"])
            table.add_row("Modo", snapshot["mode"])
            table.add_row("Contexto", snapshot["context"])
            table.add_row("URL local", snapshot["local_url"])
            table.add_row("Skills", str(snapshot["skills"]["total"]))
            table.add_row("Capacidades", str(snapshot["permissions"]["total"]))
            table.add_row("Agentes locales", ", ".join(snapshot["local_agents"]))
            self.console.print(table)
        else:
            self._write(str(snapshot))

    def _render_paths(self) -> None:
        paths = self.engine.snapshot().get("paths", {})
        if self.console and Table:
            table = Table(title="Rutas locales")
            table.add_column("Clave")
            table.add_column("Ruta", overflow="fold")
            for key, value in paths.items():
                table.add_row(key, str(value))
            self.console.print(table)
            return
        for key, value in paths.items():
            self._write(f"{key}: {value}")

    def _render_skills(self) -> None:
        skills = self.engine.desktop_runtime.skills.all()
        if self.console and Table:
            table = Table(title="Skills disponibles")
            table.add_column("Skill")
            table.add_column("Descripcion", overflow="fold")
            for skill in skills:
                table.add_row(skill.skill_id, skill.description)
            self.console.print(table)
            return
        for skill in skills:
            self._write(f"- {skill.skill_id}: {skill.description}")

    def _render_history(self) -> None:
        history = list(self.engine.history)
        if not history:
            self._write("Todavia no hay historial.")
            return
        for item in history[:6]:
            self._write(f"[{item.created_at}] {item.user_input} -> {item.resolution['skill_id']}")

    def _render_result(self, payload: dict[str, Any]) -> None:
        resolution = payload["resolution"]
        text = (
            f"Skill: {resolution['skill_id']} ({resolution['confidence']})\n"
            f"Modo: {resolution['execution_mode']}\n"
            f"Respuesta:\n{payload['response']}"
        )
        if self.console and Panel:
            self.console.print(Panel(text, title=payload["agent"], border_style="cyan"))
        else:
            self._write(text)

    def _write(self, text: str) -> None:
        if self.console:
            self.console.print(text)
        else:
            print(text)
