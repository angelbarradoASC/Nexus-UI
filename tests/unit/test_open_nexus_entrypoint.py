from __future__ import annotations

import importlib
import os
import sys


def test_open_nexus_entrypoint_configures_defaults_and_paths(monkeypatch):
    monkeypatch.delenv("NEXUS_CONTEXT", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)

    module = importlib.import_module("desktop.open_nexus_main")
    module.configure_environment()

    assert os.environ["NEXUS_CONTEXT"] == "desktop_app"
    assert os.environ["APP_PORT"] == "11430"
    assert any(path.endswith("\\app") for path in sys.path)


def test_open_nexus_entrypoint_imports_without_shell_side_effects():
    module = importlib.import_module("desktop.open_nexus_main")
    assert hasattr(module, "main")
    assert callable(module.main)
