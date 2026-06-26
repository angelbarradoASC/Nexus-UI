"""
desktop/local_agents/monitoring_agent.py
-----------------------------------------
MonitoringAgent — loop autonomo de monitorizacion del sistema local.

Corre en background desde que arranca Nexus-UI Desktop.
Detecta umbrales de CPU/RAM/disco y genera alertas.
Envia telemetria a JAINA cuando hay conexion disponible.

Tipo de agente: AUTONOMO (no necesita input del usuario).
Nivel de permisos: NIVEL 0 (sin privilegios).
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Callable

import httpx

from desktop.local_agents.hardware_agent import HardwareAgent

logger = logging.getLogger("nexus.monitoring")


class MonitoringAgent:
    """
    Agente autonomo que monitoriza el sistema local en background.

    Flujo:
      1. Cada `interval_seconds`, recoge metricas via HardwareAgent
      2. Evalua umbrales: si hay alertas, llama al callback registrado
      3. Envia metricas al endpoint local /api/metrics/ingest para que
         la UI pueda mostrarlas en tiempo real
      4. (Futuro) Envia telemetria a JAINA/Hive Mind cuando hay conexion

    El agente no bloquea. Corre en un hilo daemon via run_sync().
    """

    def __init__(
        self,
        interval_seconds: int = 30,
        local_url: str = "http://127.0.0.1:11430",
        internal_token: str = "",
    ):
        self.interval = interval_seconds
        self.local_url = local_url
        self.internal_token = internal_token
        self.hardware = HardwareAgent()
        self.running = False
        self._alert_callback: Callable | None = None
        self._last_metrics: dict = {}

    def on_alert(self, callback: Callable):
        """
        Registra un callback que se llama cuando se detecta un umbral.

        Firma: callback(alerts: list[dict]) -> None
        """
        self._alert_callback = callback

    def run_sync(self):
        """
        Ejecuta el loop de monitorizacion de forma sincrona.
        Disenado para correr en un hilo daemon via threading.Thread.
        """
        logger.info(f"MonitoringAgent arrancado (intervalo: {self.interval}s)")
        self.running = True

        # Primer ciclo con CPU warm-up (necesita dos llamadas para valor util)
        import psutil
        psutil.cpu_percent(interval=None)
        time.sleep(1)

        while self.running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Error en ciclo de monitorizacion: {e}", exc_info=True)
            time.sleep(self.interval)

        logger.info("MonitoringAgent detenido")

    def stop(self):
        """Detiene el loop en el proximo ciclo."""
        self.running = False

    def get_last_metrics(self) -> dict:
        """Devuelve las ultimas metricas recogidas (sin llamar al hardware)."""
        return self._last_metrics

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _tick(self):
        """Un ciclo de monitorizacion."""
        metrics = self.hardware.get_metrics()
        if "error" in metrics:
            return

        metrics["collected_at"] = datetime.now().isoformat()
        self._last_metrics = metrics

        # Evaluar umbrales
        alerts = self.hardware.check_thresholds(metrics)
        if alerts:
            logger.warning(f"Alertas detectadas: {[a['message'] for a in alerts]}")
            if self._alert_callback:
                try:
                    self._alert_callback(alerts)
                except Exception as e:
                    logger.error(f"Error en callback de alertas: {e}")

        # Enviar metricas al servidor local (no critico si falla)
        self._push_metrics(metrics, alerts)

    def _push_metrics(self, metrics: dict, alerts: list):
        """
        Envia metricas al endpoint local para que la UI las muestre.
        Fallo silencioso: si el servidor no esta listo, se ignora.
        """
        try:
            headers = {}
            if self.internal_token:
                headers["Authorization"] = f"Bearer {self.internal_token}"
            httpx.post(
                f"{self.local_url}/api/metrics/ingest",
                json={"metrics": metrics, "alerts": alerts},
                headers=headers,
                timeout=3.0,
            )
        except Exception:
            # Silencioso: el servidor puede no estar listo todavia
            pass
