"""Subsistema RDP de Desktop: lanzar mstsc.exe, log de sesiones, watcher."""

from __future__ import annotations

import ipaddress
import json
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from desktop.storage.local_state import DesktopLocalState
from products.desktop.backend.dependencies import get_desktop_local_state

router = APIRouter()

_rdp_log_lock = threading.Lock()


class _DesktopRdpLaunchBody(BaseModel):
    host: str


def _rdp_session_log_path(local_state: DesktopLocalState) -> Path:
    local_state.ensure_layout()
    return local_state.logs_dir / "rdp_sessions.jsonl"


def _append_rdp_session_log(local_state: DesktopLocalState, payload: dict[str, Any]) -> None:
    path = _rdp_session_log_path(local_state)
    with _rdp_log_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _watch_rdp_process(
    local_state: DesktopLocalState, process: subprocess.Popen[Any], session_id: str, host: str, pid: int
) -> None:
    try:
        exit_code = process.wait()
        finished_at = datetime.now().isoformat()
        logger.info(
            "Sesion RDP terminada | session_id={} | host={} | pid={} | exit_code={}",
            session_id, host, pid, exit_code,
        )
        _append_rdp_session_log(
            local_state,
            {
                "event": "ended", "session_id": session_id, "host": host,
                "pid": pid, "exit_code": exit_code, "finished_at": finished_at,
            },
        )
    except Exception as exc:
        logger.warning(
            "No se pudo observar el cierre de la sesion RDP | session_id={} | host={} | error={}",
            session_id, host, exc,
        )


@router.post("/api/desktop/operator/rdp")
async def launch_desktop_rdp(
    body: _DesktopRdpLaunchBody,
    local_state: DesktopLocalState = Depends(get_desktop_local_state),
):
    host = body.host.strip()
    if not host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Debes indicar una IP")

    try:
        parsed_host = ipaddress.ip_address(host).compressed
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "IP no valida") from exc

    session_id = f"rdp-{uuid.uuid4().hex[:12]}"
    started_at = datetime.now().isoformat()

    try:
        process = subprocess.Popen(["mstsc.exe", f"/v:{parsed_host}"], shell=False)
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Cliente RDP no disponible en este equipo",
        ) from exc
    except Exception as exc:
        logger.exception(
            "No se pudo lanzar la sesion RDP | session_id={} | host={}",
            session_id, parsed_host,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"No se pudo abrir el cliente RDP: {exc}",
        ) from exc

    logger.info("Sesion RDP iniciada | session_id={} | host={} | pid={}", session_id, parsed_host, process.pid)
    _append_rdp_session_log(
        local_state,
        {"event": "started", "session_id": session_id, "host": parsed_host, "pid": process.pid, "started_at": started_at},
    )

    watcher = threading.Thread(
        target=_watch_rdp_process,
        args=(local_state, process, session_id, parsed_host, process.pid),
        daemon=True,
        name=f"rdp-watch-{session_id}",
    )
    watcher.start()

    return {
        "available": True,
        "status": "launched",
        "session_id": session_id,
        "host": parsed_host,
        "pid": process.pid,
        "started_at": started_at,
        "log_path": str(_rdp_session_log_path(local_state)),
    }
