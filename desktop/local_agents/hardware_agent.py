"""
desktop/local_agents/hardware_agent.py
---------------------------------------
HardwareAgent — recopila metricas del hardware local.

Parte del Edge Agent (Fase 1, integrado en Nexus-UI Desktop).
Sin privilegios requeridos: solo lectura via psutil.
"""

import logging
import platform
import time
from typing import Any

import psutil

logger = logging.getLogger("nexus.hardware")


class HardwareAgent:
    """
    Recopila metricas de CPU, RAM, disco, red y procesos del sistema local.

    Nivel de permisos: NIVEL 0 (sin privilegios).
    No escribe nada. Solo lectura de contadores del SO.
    """

    def get_metrics(self) -> dict[str, Any]:
        """
        Devuelve snapshot completo de metricas del sistema.
        Llamada sincrona, rapida (~100ms con cpu_percent interval=None).
        """
        try:
            cpu_freq = psutil.cpu_freq()
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            disk = psutil.disk_usage("/")
            net = psutil.net_io_counters()

            return {
                "cpu": {
                    "percent": psutil.cpu_percent(interval=None),
                    "cores_logical": psutil.cpu_count(logical=True),
                    "cores_physical": psutil.cpu_count(logical=False),
                    "freq_mhz": round(cpu_freq.current, 1) if cpu_freq else None,
                    "freq_max_mhz": round(cpu_freq.max, 1) if cpu_freq else None,
                },
                "memory": {
                    "total_gb": round(mem.total / (1024 ** 3), 2),
                    "available_gb": round(mem.available / (1024 ** 3), 2),
                    "used_gb": round(mem.used / (1024 ** 3), 2),
                    "percent": mem.percent,
                },
                "swap": {
                    "total_gb": round(swap.total / (1024 ** 3), 2),
                    "used_gb": round(swap.used / (1024 ** 3), 2),
                    "percent": swap.percent,
                },
                "disk": {
                    "total_gb": round(disk.total / (1024 ** 3), 2),
                    "used_gb": round(disk.used / (1024 ** 3), 2),
                    "free_gb": round(disk.free / (1024 ** 3), 2),
                    "percent": disk.percent,
                },
                "network": {
                    "bytes_sent_mb": round(net.bytes_sent / (1024 ** 2), 2),
                    "bytes_recv_mb": round(net.bytes_recv / (1024 ** 2), 2),
                    "packets_sent": net.packets_sent,
                    "packets_recv": net.packets_recv,
                },
                "processes": {
                    "total": len(psutil.pids()),
                },
                "system": {
                    "platform": platform.system(),
                    "platform_version": platform.version(),
                    "hostname": platform.node(),
                    "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 2),
                },
            }
        except Exception as e:
            logger.error(f"Error obteniendo metricas: {e}", exc_info=True)
            return {"error": str(e)}

    def get_top_processes(self, limit: int = 10, sort_by: str = "cpu") -> list[dict]:
        """
        Devuelve los procesos que mas CPU o RAM consumen.

        Args:
            limit: numero maximo de procesos a devolver
            sort_by: 'cpu' o 'memory'
        """
        try:
            procs = []
            for proc in psutil.process_iter(
                ["pid", "name", "cpu_percent", "memory_percent", "status"]
            ):
                try:
                    info = proc.info
                    if info.get("cpu_percent") is not None:
                        procs.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
            procs.sort(key=lambda x: x.get(key) or 0, reverse=True)
            return procs[:limit]
        except Exception as e:
            logger.error(f"Error obteniendo procesos: {e}")
            return []

    def get_disk_partitions(self) -> list[dict]:
        """Devuelve uso de todas las particiones montadas."""
        result = []
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    result.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "free_gb": round(usage.free / (1024 ** 3), 2),
                        "percent": usage.percent,
                    })
                except (PermissionError, OSError):
                    pass
        except Exception as e:
            logger.error(f"Error en particiones: {e}")
        return result

    def check_thresholds(self, metrics: dict) -> list[dict]:
        """
        Evalua metricas contra umbrales y devuelve lista de alertas.
        Devuelve lista vacia si todo esta bien.
        """
        thresholds = {
            "cpu.percent": 85,
            "memory.percent": 90,
            "disk.percent": 95,
            "swap.percent": 80,
        }
        alerts = []
        for key, threshold in thresholds.items():
            section, field = key.split(".")
            value = metrics.get(section, {}).get(field)
            if value is not None and value > threshold:
                alerts.append({
                    "type": key,
                    "value": value,
                    "threshold": threshold,
                    "severity": "critical" if value > threshold + 10 else "warning",
                    "message": f"{key} al {value}% (umbral: {threshold}%)",
                })
        return alerts
