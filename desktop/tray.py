"""
desktop/tray.py
---------------
System tray de Nexus Desktop.

Usa pystray para crear el icono en la bandeja del sistema Windows
con accesos directos al panel operador y a acciones seguras.
"""

from __future__ import annotations

import logging
import threading

import httpx
import pystray
from PIL import Image, ImageDraw

from desktop.branding import resolve_branding_icon

logger = logging.getLogger("nexus.tray")


def _build_fallback_icon() -> Image.Image:
    """Crea un icono minimalista si no hay recurso grafico disponible."""
    size = 64
    img = Image.new("RGB", (size, size), color=(18, 60, 55))
    draw = ImageDraw.Draw(img)
    draw.rectangle([2, 2, size - 3, size - 3], outline=(169, 123, 47), width=2)
    draw.text((20, 18), "N", fill=(255, 253, 250))
    return img


def _load_icon() -> Image.Image:
    """Carga el icono de la app. Fallback a uno generado si no existe."""
    branding_icon = resolve_branding_icon()
    if branding_icon is not None:
        try:
            return Image.open(branding_icon).convert("RGB").resize((64, 64))
        except Exception as exc:
            logger.warning("No se pudo cargar icono desde %s: %s", branding_icon, exc)
    return _build_fallback_icon()


class SystemTray:
    """Gestiona el icono de bandeja y accesos al panel operativo."""

    def __init__(
        self,
        window,
        local_url: str = "http://127.0.0.1:11430",
        operator_url: str | None = None,
        internal_token: str = "",
    ) -> None:
        self.window = window
        self.local_url = local_url
        self.operator_url = operator_url or f"{local_url}/open-nexus"
        self.internal_token = internal_token
        self.icon: pystray.Icon | None = None

    def run(self) -> None:
        """Arranca el tray. Debe llamarse en un hilo separado."""
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Open-Nexus", self._show_window, default=True),
            pystray.MenuItem("Abrir outreach", self._open_outreach),
            pystray.MenuItem("Abrir panel operativo", self._open_operator_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Fichar entrada", self._fichar_entrada),
            pystray.MenuItem("Fichar salida", self._fichar_salida),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Estado del sistema", self._show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", self._quit),
        )

        self.icon = pystray.Icon(
            name="nexus-operator",
            icon=_load_icon(),
            title="Nexus Operator - JAINA",
            menu=menu,
        )
        logger.info("System tray iniciado")
        self.icon.run()

    def _show_window(self, icon=None, item=None) -> None:
        """Muestra la ventana principal enfocada al panel operador."""
        self._load_operator()

    def _open_outreach(self, icon=None, item=None) -> None:
        """Abre el shell operativo donde vive el control de outreach."""
        self._load_operator()

    def _open_operator_status(self, icon=None, item=None) -> None:
        """Abre el panel principal de Nexus Operator."""
        self._load_operator()

    def _fichar_entrada(self, icon=None, item=None) -> None:
        self._send_quick_action("fichar_entrada")

    def _fichar_salida(self, icon=None, item=None) -> None:
        self._send_quick_action("fichar_salida")

    def _show_status(self, icon=None, item=None) -> None:
        """Abre la superficie operativa en vez de un JSON crudo."""
        self._load_operator()

    def _quit(self, icon=None, item=None) -> None:
        logger.info("Saliendo de Nexus Desktop...")
        if self.icon:
            self.icon.stop()
        try:
            self.window.destroy()
        except Exception:
            pass

    def _load_operator(self) -> None:
        try:
            self.window.show()
            self.window.load_url(self.operator_url)
        except Exception as exc:
            logger.warning("No se pudo abrir la ventana principal: %s", exc)

    def _send_quick_action(self, action: str) -> None:
        """Envia una quick action al servidor local en segundo plano."""

        def _do() -> None:
            try:
                headers = {}
                if self.internal_token:
                    headers["Authorization"] = f"Bearer {self.internal_token}"
                response = httpx.post(
                    f"{self.local_url}/api/quick-action",
                    json={"action": action},
                    headers=headers,
                    timeout=10.0,
                )
                if response.status_code == 200:
                    payload = response.json()
                    message = payload.get("message", "Accion completada")
                    logger.info("Quick action '%s': %s", action, message)
                    if self.icon:
                        self.icon.notify(message, title="Open-Nexus")
                else:
                    logger.warning("Quick action '%s' fallo: %s", action, response.status_code)
            except Exception as exc:
                logger.error("Error en quick action '%s': %s", action, exc)

        threading.Thread(target=_do, daemon=True).start()

    def notify(self, message: str, title: str = "Open-Nexus") -> None:
        """Muestra una notificacion balloon desde codigo externo."""
        if self.icon:
            try:
                self.icon.notify(message, title=title)
            except Exception as exc:
                logger.debug("Notificacion no soportada: %s", exc)
