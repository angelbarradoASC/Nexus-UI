"""
app/utils/logger.py
--------------------
Configuracion estandar de Loguru para NEXUS-UI.

Uso:
    from utils.logger import setup_logging
    setup_logging()  # Llamar ANTES de cualquier import de la app
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def setup_logging(nivel: str = "INFO", archivo: Path | None = None) -> None:
    """
    Configura Loguru como sistema de logging unico.
    Intercepta tambien stdlib logging (FastAPI, uvicorn, httpx, etc).
    """
    from loguru import logger

    logger.remove()

    console_sink = _resolve_console_sink()
    effective_file = archivo or _fallback_log_file(console_sink)

    if console_sink is not None:
        logger.add(
            console_sink,
            level=nivel,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan> | "
                "{message}"
            ),
            colorize=True,
            enqueue=False,
        )

    if effective_file is not None:
        effective_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(effective_file),
            level=nivel,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} | {message}",
            rotation="1 month",
            retention="6 months",
            encoding="utf-8",
            enqueue=True,
        )

    _interceptar_stdlib(nivel)
    logger.info("Logging inicializado | nivel={} | archivo={}", nivel, effective_file)


def _resolve_console_sink():
    """Return a usable console sink when one exists."""
    candidate = getattr(sys, "stdout", None) or getattr(sys, "__stdout__", None)
    if candidate is None:
        return None
    if getattr(candidate, "closed", False):
        return None
    return candidate


def _fallback_log_file(console_sink) -> Path | None:
    """Fallback to a local file when running without an attached console."""
    if console_sink is not None:
        return None
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Open-Nexus" / "logs"
    return root / "runtime.log"


def _interceptar_stdlib(nivel: str) -> None:
    """Redirect stdlib logging to Loguru."""
    from loguru import logger

    class _InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                nivel_loguru = logger.level(record.levelname).name
            except ValueError:
                nivel_loguru = record.levelno

            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                nivel_loguru, record.getMessage()
            )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    for nombre in ("httpx", "httpcore", "urllib3", "multipart", "paramiko"):
        logging.getLogger(nombre).setLevel(logging.WARNING)
