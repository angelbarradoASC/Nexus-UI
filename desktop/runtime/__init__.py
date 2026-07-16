"""Runtime building blocks for Nexus Desktop."""

from desktop.runtime.assistant_runtime import DesktopAssistantRuntime
from desktop.runtime.capabilities import Capability, CapabilityRegistry, PermissionLevel

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "DesktopAssistantRuntime",
    "PermissionLevel",
]
