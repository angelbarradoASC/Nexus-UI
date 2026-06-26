"""Launch Nexus web reliably from the repository root."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_dir = repo_root / "app"
    host = os.getenv("NEXUS_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("NEXUS_WEB_PORT", "5010"))

    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(app_dir))
    os.chdir(app_dir)

    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
