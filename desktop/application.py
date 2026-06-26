"""Application orchestrator for Nexus Desktop."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading

from desktop.branding import resolve_windows_icon
from desktop.config import DesktopSettings
from desktop.local_agents.monitoring_agent import MonitoringAgent
from desktop.runtime.assistant_runtime import DesktopAssistantRuntime
from desktop.runtime.bootstrap import set_current_runtime
from desktop.services.local_server import LocalServer
from desktop.storage.local_state import DesktopLocalState
from desktop.tray import SystemTray

logger = logging.getLogger("nexus.desktop")

_WINDOWS_APP_ID = "Automato.OpenNexus.Desktop"
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_GCLP_HICON = -14
_GCLP_HICONSM = -34


class DesktopApplication:
    """Coordinates embedded server, local agents, tray, and native window."""

    def __init__(self, settings: DesktopSettings | None = None) -> None:
        self.settings = settings or DesktopSettings.from_env()
        self.runtime = DesktopAssistantRuntime(self.settings)
        set_current_runtime(self.runtime)
        self.local_state = DesktopLocalState(self.settings)
        self.local_state.ensure_layout()
        self.server = LocalServer(
            host=self.settings.host,
            port=self.settings.app_port,
            startup_timeout_seconds=self.settings.startup_timeout_seconds,
        )
        self.monitor = MonitoringAgent(
            interval_seconds=self.settings.monitoring_interval_seconds,
            local_url=self.settings.local_url,
            internal_token=self.settings.desktop_internal_token,
        )
        self._window_icon_handles: list[int] = []

    def run(self) -> None:
        """Start the desktop runtime and block on the native window event loop."""
        logger.info("Open-Nexus Desktop arrancando...")
        self._apply_windows_process_branding()

        self.server.start()
        if not self.server.wait_until_ready():
            logger.error(
                "El servidor local no arranco en %ss. Abortando.",
                self.settings.startup_timeout_seconds,
            )
            sys.exit(1)

        logger.info("Servidor listo en %s", self.settings.local_url)
        self._start_monitoring()
        window = self._create_window()
        self._start_tray(window)
        self._start_webview()

        logger.info("Ventana cerrada. Nexus-UI Desktop terminando.")

    def _start_monitoring(self) -> None:
        monitor_thread = threading.Thread(
            target=self.monitor.run_sync,
            daemon=True,
            name="nexus-monitor",
        )
        monitor_thread.start()

    def _create_window(self):
        import webview

        launch_url = self.settings.startup_url if self.settings.open_operator_on_start else self.settings.local_url
        window = webview.create_window(
            title="Open-Nexus",
            url=launch_url,
            width=1400,
            height=900,
            resizable=True,
            maximized=True,
            min_size=(900, 600),
            text_select=True,
            confirm_close=False,
        )
        window.events.shown += self._on_window_shown
        return window

    def _start_tray(self, window) -> None:
        tray = SystemTray(
            window,
            local_url=self.settings.local_url,
            operator_url=self.settings.startup_url,
            internal_token=self.settings.desktop_internal_token,
        )
        tray_thread = threading.Thread(
            target=tray.run,
            daemon=True,
            name="nexus-tray",
        )
        tray_thread.start()

    def _start_webview(self) -> None:
        import webview

        branding_icon = resolve_windows_icon()
        webview.start(
            debug=self.settings.debug,
            http_server=False,
            icon=str(branding_icon) if branding_icon else None,
        )

    def _on_window_shown(self, *_args) -> None:
        self._apply_windows_window_branding()

    def _apply_windows_process_branding(self) -> None:
        if os.name != "nt":
            return

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_ID)
        except Exception as exc:
            logger.warning("No se pudo fijar AppUserModelID de Windows: %s", exc)

    def _apply_windows_window_branding(self) -> None:
        if os.name != "nt":
            return

        branding_icon = resolve_windows_icon()
        if branding_icon is None:
            logger.warning("No se encontro icono de branding para la ventana desktop")
            return

        try:
            import webview

            native_window = webview.windows[0].native if webview.windows else None
            if native_window is None:
                logger.warning("No hay ventana nativa pywebview para aplicar branding")
                return

            handle_attr = getattr(native_window, "Handle", None)
            if handle_attr is None:
                logger.warning("La ventana nativa no expone Handle")
                return

            hwnd = int(handle_attr.ToInt64())
            small_icon = ctypes.windll.user32.LoadImageW(
                None,
                str(branding_icon),
                _IMAGE_ICON,
                16,
                16,
                _LR_LOADFROMFILE,
            )
            big_icon = ctypes.windll.user32.LoadImageW(
                None,
                str(branding_icon),
                _IMAGE_ICON,
                32,
                32,
                _LR_LOADFROMFILE,
            )

            if small_icon:
                ctypes.windll.user32.SendMessageW(hwnd, _WM_SETICON, _ICON_SMALL, small_icon)
                ctypes.windll.user32.SetClassLongPtrW(hwnd, _GCLP_HICONSM, small_icon)
                self._window_icon_handles.append(int(small_icon))
            if big_icon:
                ctypes.windll.user32.SendMessageW(hwnd, _WM_SETICON, _ICON_BIG, big_icon)
                ctypes.windll.user32.SetClassLongPtrW(hwnd, _GCLP_HICON, big_icon)
                self._window_icon_handles.append(int(big_icon))

            logger.info("Branding nativo de ventana aplicado | hwnd=%s | icon=%s", hwnd, branding_icon)
        except Exception as exc:
            logger.warning("No se pudo aplicar icono nativo de ventana: %s", exc)
