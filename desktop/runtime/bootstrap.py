"""Shared access to the current desktop runtime."""

from __future__ import annotations

from desktop.runtime.assistant_runtime import DesktopAssistantRuntime

_current_runtime: DesktopAssistantRuntime | None = None


def set_current_runtime(runtime: DesktopAssistantRuntime) -> None:
    global _current_runtime
    _current_runtime = runtime


def get_current_runtime() -> DesktopAssistantRuntime | None:
    return _current_runtime
