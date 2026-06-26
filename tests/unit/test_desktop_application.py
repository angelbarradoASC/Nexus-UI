from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

from desktop.config import DesktopSettings


import types


def _import_desktop_application():
    fake_pystray = types.SimpleNamespace(
        Icon=MagicMock,
        Menu=lambda *items: list(items),
        MenuItem=lambda *args, **kwargs: {"args": args, "kwargs": kwargs},
    )
    fake_pystray.Menu.SEPARATOR = "separator"

    fake_pil_image = types.SimpleNamespace(new=MagicMock())
    fake_pil_imagedraw = types.SimpleNamespace(Draw=MagicMock())
    fake_pil = types.SimpleNamespace(Image=fake_pil_image, ImageDraw=fake_pil_imagedraw)

    with patch.dict(
        sys.modules,
        {
            "pystray": fake_pystray,
            "PIL": fake_pil,
            "PIL.Image": fake_pil_image,
            "PIL.ImageDraw": fake_pil_imagedraw,
        },
    ):
        module = importlib.import_module("desktop.application")
        module = importlib.reload(module)
    return module


def test_desktop_application_crea_ventana_en_panel_operador():
    module = _import_desktop_application()
    settings = DesktopSettings(
        app_port=11430,
        host="127.0.0.1",
        startup_route="/open-nexus",
        open_operator_on_start=True,
        desktop_internal_token="token-123",
    )

    fake_window_module = types.SimpleNamespace(create_window=MagicMock())
    with patch("desktop.application.set_current_runtime"), \
         patch("desktop.application.LocalServer"), \
         patch("desktop.application.MonitoringAgent"), \
         patch.dict(sys.modules, {"webview": fake_window_module}):
        app = module.DesktopApplication(settings)
        app._create_window()

    _, kwargs = fake_window_module.create_window.call_args
    assert kwargs["title"] == "Open-Nexus"
    assert kwargs["url"] == "http://127.0.0.1:11430/open-nexus"


def test_desktop_application_pasa_operator_url_al_tray():
    module = _import_desktop_application()
    settings = DesktopSettings(
        app_port=11430,
        host="127.0.0.1",
        startup_route="/open-nexus",
        open_operator_on_start=True,
        desktop_internal_token="token-123",
    )

    with patch("desktop.application.set_current_runtime"), \
         patch("desktop.application.LocalServer"), \
         patch("desktop.application.MonitoringAgent"), \
         patch("desktop.application.SystemTray") as tray_cls:
        app = module.DesktopApplication(settings)
        window = MagicMock()
        app._start_tray(window)

    _, kwargs = tray_cls.call_args
    assert kwargs["operator_url"] == "http://127.0.0.1:11430/open-nexus"
