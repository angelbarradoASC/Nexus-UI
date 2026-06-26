"""Legacy compatibility import. Canonical desktop backend lives in products.desktop.backend.app."""

from products.desktop.backend.app import app, lifespan

__all__ = ["app", "lifespan"]

