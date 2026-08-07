"""
app/utils/logger.py
--------------------
Configuracion estandar de Loguru para NEXUS-UI.

Uso:
    from utils.logger import setup_logging
    setup_logging()  # Llamar ANTES de cualquier import de la app

Dos capas separadas, no una:
    - Ficheros por categoria (app/llm/prospecting/http/pepo/desktop) — registro
      completo, para bucear cuando hace falta investigar algo a fondo.
    - hitos.log — solo los eventos que cuentan la historia (peticion recibida,
      que se decidio, que se hizo, que se respondio). Se escribe con hito(),
      no con logger.info() normal — logger.info() nunca llega aqui.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Particion de logs por funcion: cada categoria escribe en su propio fichero
# (mismo directorio que el fichero principal) en vez de mezclarse todos en uno.
# La consola sigue mostrando todo sin filtrar, solo se particionan los ficheros.
#
# "app" es el cajon de lo que no matchea ninguna categoria — deberia quedar
# casi vacio; si algo aparece ahi a menudo, probablemente le falta su propio
# prefijo aqui (paso por alto real detectado 2026-08-06: nexus.mouse_agent y
# nexus.system_task_agent — el PEPO de verdad — caian en "app" en vez de
# "pepo" porque sus nombres de logger no matcheaban ningun prefijo).
_CATEGORY_PREFIXES: dict[str, tuple[str, ...]] = {
    "llm": ("agents.llm_router", "agents.llm_watchdog", "agents.generation_agent", "agents.intention_agent"),
    "prospecting": ("nexus.prospecting",),
    "http": ("uvicorn",),
    "pepo": (
        "nexus.teams", "nexus.mail", "nexus.pepo",
        "nexus.mouse_agent", "nexus.system_task_agent", "nexus.hardware",
    ),
    "desktop": ("desktop.", "nexus.tray", "nexus.monitoring", "nexus.desktop", "utils.session_auth"),
}


def _categorize(record_name: str) -> str:
    for category, prefixes in _CATEGORY_PREFIXES.items():
        if record_name.startswith(prefixes):
            return category
    return "app"


def hito(mensaje: str, **campos) -> None:
    """
    Registra un HITO: un evento que cuenta la historia de lo que hizo la app
    (peticion recibida, decision tomada, accion ejecutada, respuesta dada).

    Va SOLO a hitos.log (ademas de su fichero de categoria normal, via el
    logger.info subyacente) — nunca uses logger.info() para esto si quieres
    que aparezca en el log ordenado; usa hito().
    """
    from loguru import logger

    logger.bind(hito=True).info(mensaje, **campos)


_SIN_ESPECIFICAR = object()  # distingue "no se paso archivo" (usar default) de "archivo=None explicito" (sin fichero)


def setup_logging(nivel: str = "INFO", archivo=_SIN_ESPECIFICAR) -> None:
    """
    Configura Loguru como sistema de logging unico.
    Intercepta tambien stdlib logging (FastAPI, uvicorn, httpx, etc).

    Los ficheros se particionan por funcion (app/llm/prospecting/http/pepo/
    desktop) para evitar tener toda la actividad mezclada en un unico fichero,
    mas un hitos.log aparte con solo los eventos marcados via hito().
    """
    from loguru import logger

    logger.remove()

    console_sink = _resolve_console_sink()
    effective_file = _fallback_log_file() if archivo is _SIN_ESPECIFICAR else archivo

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
        for category in ("app", *_CATEGORY_PREFIXES.keys()):
            file_path = effective_file if category == "app" else effective_file.with_name(f"{category}.log")
            logger.add(
                str(file_path),
                level=nivel,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} | {message}",
                rotation="1 month",
                retention="6 months",
                encoding="utf-8",
                # enqueue=True (cola en hilo de fondo) se probo y en este proceso
                # concreto no drenaba nunca — los ficheros ni se llegaban a crear.
                # Escritura sincrona: mas simple y de hecho mas fiable aqui.
                enqueue=False,
                filter=(lambda record, cat=category: _categorize(record["name"]) == cat),
            )

        # hitos.log — solo records marcados con hito(). Formato mas legible,
        # sin nombre de logger tecnico, pensado para leerse de un vistazo.
        logger.add(
            str(effective_file.with_name("hitos.log")),
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
            rotation="1 month",
            retention="6 months",
            encoding="utf-8",
            enqueue=False,
            filter=lambda record: bool(record["extra"].get("hito")),
        )

    _interceptar_stdlib(nivel)
    logger.info(
        "Logging inicializado | nivel={} | directorio={} | ficheros=app,llm,prospecting,http,pepo,desktop,hitos",
        nivel,
        effective_file.parent if effective_file is not None else None,
    )


def _resolve_console_sink():
    """Return a usable console sink when one exists, forzando UTF-8.

    Sin esto, la consola de Windows (cp1252 por defecto) revienta con
    UnicodeEncodeError en cualquier mensaje con flecha (→) u otros
    caracteres fuera de cp1252, y el mensaje se pierde en silencio (solo
    queda el rastro de "Logging error in Loguru Handler").
    """
    candidate = getattr(sys, "stdout", None) or getattr(sys, "__stdout__", None)
    if candidate is None:
        return None
    if getattr(candidate, "closed", False):
        return None
    if hasattr(candidate, "reconfigure"):
        try:
            candidate.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    return candidate


def _fallback_log_file() -> Path:
    """
    Ruta fija del directorio de logs, siempre absoluta — antes esto solo se
    usaba sin consola y products/desktop/backend/app.py pasaba una ruta
    relativa ("logs/nexus.log") como fallback "normal", que resolvia contra
    el directorio de lanzamiento del proceso: mismo codigo, logs en un sitio
    distinto segun desde donde se arrancara la app. Ahora siempre es la misma.
    """
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Open-Nexus" / "logs"
    return root / "nexus.log"


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
