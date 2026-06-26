"""Shared branding helpers for Nexus Desktop."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_UI_STATIC_DIR = REPO_ROOT / "products" / "desktop" / "ui" / "static"
CANONICAL_ANCHOR_ICO = DESKTOP_UI_STATIC_DIR / "nexus_anchor.ico"
CANONICAL_ANCHOR_PNG = DESKTOP_UI_STATIC_DIR / "nexus_anchor.png"


def get_branding_icon_candidates() -> list[Path]:
    """Return preferred branding assets ordered from best to worst."""
    return [
        CANONICAL_ANCHOR_ICO,
        CANONICAL_ANCHOR_PNG,
        DESKTOP_UI_STATIC_DIR / "favicon.ico",
        DESKTOP_UI_STATIC_DIR / "jaina.png",
        DESKTOP_UI_STATIC_DIR / "jaina.jpg",
        REPO_ROOT / "app" / "static" / "favicon.ico",
    ]


def resolve_branding_icon() -> Path | None:
    """Resolve the first existing branding asset on disk."""
    for candidate in get_branding_icon_candidates():
        if candidate.exists():
            return candidate
    return None


def get_windows_icon_candidates() -> list[Path]:
    """Return only `.ico` files suitable for Windows window/taskbar branding."""
    return [
        CANONICAL_ANCHOR_ICO,
        DESKTOP_UI_STATIC_DIR / "favicon.ico",
        REPO_ROOT / "app" / "static" / "favicon.ico",
    ]


def resolve_windows_icon() -> Path | None:
    """Resolve the preferred `.ico` asset for Windows-native surfaces."""
    for candidate in get_windows_icon_candidates():
        if candidate.exists():
            return candidate
    return None
