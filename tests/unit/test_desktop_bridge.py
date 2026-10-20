"""tests/unit/test_desktop_bridge.py

Puente JS -> Python de la ventana nativa (selector de carpetas del modo codigo).
pywebview expone a la pagina TODOS los metodos publicos del objeto `js_api`, asi
que se comprueba que la superficie es exactamente una: pick_folder.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

from desktop.bridge import DesktopBridge


def _fake_webview() -> types.SimpleNamespace:
    return types.SimpleNamespace(FOLDER_DIALOG=20, create_window=MagicMock())


def test_the_only_public_surface_is_pick_folder():
    public = {name for name in dir(DesktopBridge) if not name.startswith("_")}

    assert public == {"pick_folder"}


def test_pick_folder_returns_the_chosen_path_and_opens_a_folder_dialog():
    window = MagicMock()
    window.create_file_dialog.return_value = (r"C:\DEV\mi-proyecto",)
    bridge = DesktopBridge()
    bridge._attach(window)

    with patch.dict(sys.modules, {"webview": _fake_webview()}):
        chosen = bridge.pick_folder(r"C:\DEV")

    assert chosen == r"C:\DEV\mi-proyecto"
    window.create_file_dialog.assert_called_once_with(20, directory=r"C:\DEV", allow_multiple=False)


def test_pick_folder_returns_none_when_the_user_cancels():
    window = MagicMock()
    bridge = DesktopBridge()
    bridge._attach(window)

    with patch.dict(sys.modules, {"webview": _fake_webview()}):
        window.create_file_dialog.return_value = None
        assert bridge.pick_folder() is None
        window.create_file_dialog.return_value = ()
        assert bridge.pick_folder() is None


def test_pick_folder_without_a_window_or_when_the_dialog_fails_returns_none():
    assert DesktopBridge().pick_folder() is None

    window = MagicMock()
    window.create_file_dialog.side_effect = RuntimeError("sin interfaz")
    bridge = DesktopBridge()
    bridge._attach(window)
    with patch.dict(sys.modules, {"webview": _fake_webview()}):
        assert bridge.pick_folder() is None


def test_the_desktop_window_is_created_with_the_bridge_attached():
    from tests.unit.test_desktop_application import _import_desktop_application
    from desktop.config import DesktopSettings

    module = _import_desktop_application()
    settings = DesktopSettings(
        app_port=11430, host="127.0.0.1", startup_route="/open-nexus", open_operator_on_start=True,
        desktop_internal_token="token-123",
    )
    fake = types.SimpleNamespace(create_window=MagicMock())
    with patch("desktop.application.set_current_runtime"), \
         patch("desktop.application.LocalServer"), \
         patch("desktop.application.MonitoringAgent"), \
         patch.dict(sys.modules, {"webview": fake}):
        module.DesktopApplication(settings)._create_window()

    bridge = fake.create_window.call_args.kwargs["js_api"]
    assert isinstance(bridge, DesktopBridge)
    assert bridge._window is fake.create_window.return_value
