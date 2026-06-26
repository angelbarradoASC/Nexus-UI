"""Local FastAPI server bootstrap for Nexus Desktop."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path

from desktop.path_setup import ensure_desktop_import_paths


def _server_trace(message: str) -> None:
    try:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Open-Nexus"
        root.mkdir(parents=True, exist_ok=True)
        trace_path = root / "bootstrap.log"
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat()} {message}\n")
    except Exception:
        pass


class LocalServer:
    """Starts and waits for the embedded FastAPI app."""

    def __init__(self, *, host: str, port: int, startup_timeout_seconds: int) -> None:
        self.host = host
        self.port = port
        self.startup_timeout_seconds = startup_timeout_seconds
        self._thread: threading.Thread | None = None
        self._boot_error: BaseException | None = None

    @property
    def local_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> threading.Thread:
        """Start the FastAPI app in a background thread."""
        thread = threading.Thread(
            target=self._start_server,
            daemon=True,
            name="nexus-server",
        )
        thread.start()
        self._thread = thread
        return thread

    def wait_until_ready(self) -> bool:
        """Poll the embedded health endpoint until it responds or times out."""
        import httpx

        deadline = time.time() + self.startup_timeout_seconds
        with httpx.Client(trust_env=False) as client:
            while time.time() < deadline:
                if self._thread is not None and not self._thread.is_alive():
                    _server_trace(
                        "local_server thread exited before readiness "
                        f"error={self._boot_error!r}"
                    )
                    return False
                try:
                    response = client.get(f"{self.local_url}/health", timeout=1.0)
                    if response.is_success:
                        _server_trace("local_server health probe succeeded")
                        return True
                except Exception as exc:
                    _server_trace(f"local_server health probe pending: {exc!r}")
                    time.sleep(0.3)
        return False

    def _start_server(self) -> None:
        """Import and run the embedded FastAPI application."""
        import uvicorn

        try:
            _server_trace("local_server starting import paths")
            ensure_desktop_import_paths()
            from products.desktop.backend.app import app as fastapi_app
            _server_trace("local_server imported desktop backend app")
            config = uvicorn.Config(
                fastapi_app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
                log_config=None,
            )
            server = uvicorn.Server(config)
            server.install_signal_handlers = lambda: None
            _server_trace(f"local_server running uvicorn host={self.host} port={self.port}")
            server.run()
            _server_trace("local_server uvicorn server.run returned")
        except BaseException as exc:
            self._boot_error = exc
            _server_trace(f"local_server server bootstrap failed: {exc!r}")
            raise
