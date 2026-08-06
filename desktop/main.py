"""
desktop/main.py
---------------
Thin entry point for Nexus Desktop.

The desktop app embeds the web application locally, adds a native window,
starts background local agents, and exposes system tray actions.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from path_setup import ensure_desktop_import_paths  # noqa: E402

ensure_desktop_import_paths()


def _bootstrap_trace(message: str) -> None:
    try:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Open-Nexus"
        root.mkdir(parents=True, exist_ok=True)
        trace_path = root / "bootstrap.log"
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat()} {message}\n")
    except Exception:
        pass

os.environ.setdefault("NEXUS_CONTEXT", "desktop_app")
os.environ.setdefault("APP_PORT", "11430")
os.environ.setdefault("DEBUG", "false")
# windows-use manda telemetria a PostHog por defecto — la desactivamos aqui
# tambien, por si acaso el .env no se localiza antes de que el paquete la lea.
os.environ["ANONYMIZED_TELEMETRY"] = "False"
_bootstrap_trace(
    "desktop.main bootstrap env "
    f"context={os.environ.get('NEXUS_CONTEXT')} "
    f"port={os.environ.get('APP_PORT')} "
    f"debug={os.environ.get('DEBUG')}"
)

from desktop.application import DesktopApplication
_bootstrap_trace("desktop.main imported DesktopApplication")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
)


def main() -> None:
    _bootstrap_trace("desktop.main entering main()")
    DesktopApplication().run()


if __name__ == "__main__":
    main()
