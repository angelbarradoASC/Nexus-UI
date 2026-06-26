"""
app/nexus/cmdb/source.py
--------------------------
Abstracción CMDBSource + implementación FileCMDB.

Añadir una nueva fuente = subclasificar CMDBSource e implementar
list_devices() y get_device(). El resto del sistema no cambia.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from nexus.cmdb.models import Device


# ── Interfaz ──────────────────────────────────────────────────────────────────

class CMDBSource(ABC):
    @abstractmethod
    async def list_devices(self, enabled_only: bool = True) -> list[Device]: ...

    @abstractmethod
    async def get_device(self, device_id: str) -> Device | None: ...

    async def find_by_ip(self, ip: str) -> Device | None:
        devices = await self.list_devices(enabled_only=False)
        return next((d for d in devices if d.ip == ip), None)


# ── FileCMDB — implementación local sobre JSON ────────────────────────────────

class FileCMDB(CMDBSource):
    """
    CMDB basado en un fichero JSON local.

    El fichero es un array de objetos Device serializado.
    Si no existe se crea vacío.
    Seguro para uso desde asyncio (operaciones de disco via to_thread).
    """

    def __init__(self, path: str | Path = "data/cmdb/devices.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, data: list[dict[str, Any]]) -> None:
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Lectura ───────────────────────────────────────────────────────────────

    async def list_devices(self, enabled_only: bool = True) -> list[Device]:
        raw = await asyncio.to_thread(self._load)
        devices = [Device.from_dict(d) for d in raw]
        if enabled_only:
            devices = [d for d in devices if d.enabled]
        return devices

    async def get_device(self, device_id: str) -> Device | None:
        raw = await asyncio.to_thread(self._load)
        for d in raw:
            if d.get("device_id") == device_id:
                return Device.from_dict(d)
        return None

    # ── Escritura ─────────────────────────────────────────────────────────────

    async def create(self, device: Device) -> Device:
        if not device.device_id:
            device.device_id = f"dev-{uuid.uuid4().hex[:10]}"

        def _write():
            data = self._load()
            if any(d.get("device_id") == device.device_id for d in data):
                raise ValueError(f"device_id ya existe: {device.device_id}")
            data.append(device.to_dict())
            self._save(data)

        await asyncio.to_thread(_write)
        return device

    async def update(self, device: Device) -> Device:
        def _write():
            data = self._load()
            for i, d in enumerate(data):
                if d.get("device_id") == device.device_id:
                    data[i] = device.to_dict()
                    self._save(data)
                    return
            raise ValueError(f"Device no encontrado: {device.device_id}")

        await asyncio.to_thread(_write)
        return device

    async def delete(self, device_id: str) -> bool:
        def _write():
            data = self._load()
            original = len(data)
            data = [d for d in data if d.get("device_id") != device_id]
            if len(data) < original:
                self._save(data)
                return True
            return False

        return await asyncio.to_thread(_write)

    async def upsert(self, device: Device) -> Device:
        """Crea o actualiza. Útil para imports desde MonBomb/NetBox."""
        existing = await self.get_device(device.device_id)
        if existing:
            return await self.update(device)
        return await self.create(device)
