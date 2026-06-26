"""Legacy compatibility shim for the old browser UI router.

Canonical routes:
- Desktop product: ``products.desktop.routes.ui``
- Legacy web product: ``products.web.routes.ui``
"""

from products.web.routes.ui import router

__all__ = ["router"]
