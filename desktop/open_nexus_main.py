"""Console entrypoint for Open-Nexus."""

from __future__ import annotations

import logging
import os

from desktop.path_setup import ensure_desktop_import_paths

ensure_desktop_import_paths()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
)


def configure_environment() -> None:
    """Set default desktop environment variables before heavy imports happen."""
    os.environ.setdefault("NEXUS_CONTEXT", "desktop_app")
    os.environ.setdefault("APP_PORT", "11430")


def main() -> None:
    configure_environment()
    from desktop.opennexus.shell import OpenNexusShell

    OpenNexusShell().run()


if __name__ == "__main__":
    main()
