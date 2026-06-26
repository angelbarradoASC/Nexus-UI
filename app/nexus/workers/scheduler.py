"""
app/nexus/workers/scheduler.py
---------------------------------
Scheduler APScheduler para trabajos diarios de NEXUS.
Único punto de entrada para registrar jobs asíncronos.

Uso típico desde lifespan de FastAPI:
    scheduler = NexusScheduler()
    scheduler.attach_campaign_agent(agent)
    scheduler.start()
    ...
    scheduler.stop()
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger


class NexusScheduler:
    """
    Wrapper sobre AsyncIOScheduler.
    Gestiona el job diario de prospección + jobs futuros.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="Europe/Madrid")
        self._campaign_agent = None
        self._last_run_report: dict[str, Any] | None = None
        self._last_run_at: str | None = None
        self._running: bool = False

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def attach_campaign_agent(self, agent) -> None:
        """Registra el agente de campaña antes de start()."""
        self._campaign_agent = agent

    def start(self) -> None:
        if self._running:
            return
        self._scheduler.add_job(
            self._run_daily_campaign,
            trigger="cron",
            hour=9,
            minute=0,
            id="daily_prospecting",
            replace_existing=True,
            misfire_grace_time=3600,  # tolera hasta 1h de retraso (ej. si la máquina estaba apagada)
        )
        self._scheduler.start()
        self._running = True
        logger.info("NexusScheduler iniciado | daily_prospecting a las 09:00 Europe/Madrid")

    def stop(self) -> None:
        if self._running and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("NexusScheduler detenido")

    # ── Job diario ────────────────────────────────────────────────────────────

    async def _run_daily_campaign(self) -> None:
        if self._campaign_agent is None:
            logger.warning("daily_prospecting: no hay campaign agent configurado")
            return
        logger.info("daily_prospecting: iniciando ciclo diario")
        try:
            report = await self._campaign_agent.run_daily()
            self._last_run_report = report
            self._last_run_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            logger.error("daily_prospecting: error no controlado: {}", exc)
            self._last_run_report = {"status": "error", "error": str(exc)}
            self._last_run_at = datetime.now(timezone.utc).isoformat()

    # ── Trigger manual ────────────────────────────────────────────────────────

    async def trigger_now(self) -> dict[str, Any]:
        """Ejecuta el ciclo diario inmediatamente (para tests/trigger manual desde API)."""
        if self._campaign_agent is None:
            return {"status": "error", "error": "campaign_agent_not_configured"}
        logger.info("NexusScheduler: trigger manual de daily_prospecting")
        await self._run_daily_campaign()
        return self._last_run_report or {"status": "completed"}

    # ── Estado ────────────────────────────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        next_run: str | None = None
        try:
            job = self._scheduler.get_job("daily_prospecting")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()
        except Exception:
            pass

        return {
            "running":          self._running,
            "last_run_at":      self._last_run_at,
            "last_run_report":  self._last_run_report,
            "next_run_at":      next_run,
        }
