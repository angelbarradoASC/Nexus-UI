"""
desktop/bridge.py
--------------------
Puente JavaScript -> Python de la ventana nativa (pywebview `js_api`).

Deliberadamente MINIMO: pywebview expone a la pagina TODOS los metodos publicos de
este objeto, asi que aqui solo existe lo que la interfaz no puede hacer sola. Hoy,
elegir una carpeta con el dialogo nativo de Windows (modo codigo de PEPO). Devuelve
solo la ruta que el usuario elige; no lee ni escribe ningun fichero. Que esa carpeta
quede autorizada lo decide luego el servidor (POST /api/desktop/code/workspaces),
que la valida igual que si se hubiera escrito a mano.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nexus.desktop.bridge")


class DesktopBridge:
    def __init__(self) -> None:
        self._window: Any | None = None

    def _attach(self, window: Any) -> None:
        # Con guion bajo a proposito: pywebview no expone los nombres privados a la pagina.
        self._window = window

    def pick_folder(self, start_dir: str = "") -> str | None:
        """Abre el selector de carpetas nativo. None si se cancela o no hay ventana."""
        if self._window is None:
            return None
        import webview

        try:
            chosen = self._window.create_file_dialog(
                webview.FOLDER_DIALOG, directory=str(start_dir or ""), allow_multiple=False
            )
        except Exception:
            logger.exception("No se pudo abrir el selector de carpetas")
            return None
        return str(chosen[0]) if chosen else None
