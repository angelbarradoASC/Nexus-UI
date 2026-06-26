"""Open-Nexus desktop shell package."""

from __future__ import annotations

__all__ = ["OpenNexusEngine"]


def __getattr__(name: str):
    if name == "OpenNexusEngine":
        from .engine import OpenNexusEngine

        return OpenNexusEngine
    raise AttributeError(name)
