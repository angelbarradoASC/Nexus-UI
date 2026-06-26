"""
run_preview.py
--------------
Script de arranque para el preview de Open-Nexus Desktop (sin ventana nativa).
Expone solo el backend FastAPI en el puerto 11430.
"""

import os
import sys
from pathlib import Path

# Añadir repo_root y app/ al path antes de cualquier import de la app
repo_root = Path(__file__).resolve().parent
app_root  = repo_root / "app"
for p in (str(repo_root), str(app_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("NEXUS_CONTEXT", "desktop_app")
os.environ.setdefault("APP_PORT",      "11430")

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "products.desktop.backend.app:app",
        host="127.0.0.1",
        port=11430,
        reload=False,
        log_level="info",
    )
