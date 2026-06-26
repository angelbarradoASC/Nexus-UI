"""
app/nexus/api/routes/cmdb.py
------------------------------
CRUD de dispositivos CMDB. Sin credenciales — eso va al vault.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_cmdb
from nexus.cmdb.models import Device
from nexus.cmdb.source import FileCMDB

router = APIRouter()


class DeviceIn(BaseModel):
    name:                str
    ip:                  str
    type:                str = "server"
    management_protocol: str = "ssh"
    os:                  str = ""
    vendor:              str = ""
    fqdn:                str | None = None
    port:                int = 22
    tags:                dict = {}
    notes:               str = ""
    device_id:           str | None = None


@router.get("/cmdb/devices")
async def list_devices(
    enabled_only: bool = True,
    cmdb: FileCMDB = Depends(get_cmdb),
) -> dict[str, object]:
    devices = await cmdb.list_devices(enabled_only=enabled_only)
    return {"total": len(devices), "devices": [d.to_dict() for d in devices]}


@router.get("/cmdb/devices/{device_id}")
async def get_device(
    device_id: str,
    cmdb: FileCMDB = Depends(get_cmdb),
) -> dict[str, object]:
    device = await cmdb.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    return device.to_dict()


@router.post("/cmdb/devices")
async def create_device(
    body: DeviceIn,
    cmdb: FileCMDB = Depends(get_cmdb),
) -> dict[str, object]:
    import uuid
    device = Device(
        device_id=body.device_id or f"dev-{uuid.uuid4().hex[:10]}",
        name=body.name,
        ip=body.ip,
        type=body.type,
        management_protocol=body.management_protocol,
        os=body.os,
        vendor=body.vendor,
        fqdn=body.fqdn,
        port=body.port,
        tags=body.tags,
        notes=body.notes,
    )
    created = await cmdb.create(device)
    return {"ok": True, "device": created.to_dict()}


@router.put("/cmdb/devices/{device_id}")
async def update_device(
    device_id: str,
    body: DeviceIn,
    cmdb: FileCMDB = Depends(get_cmdb),
) -> dict[str, object]:
    existing = await cmdb.get_device(device_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    updated = Device(
        device_id=device_id,
        name=body.name,
        ip=body.ip,
        type=body.type,
        management_protocol=body.management_protocol,
        os=body.os,
        vendor=body.vendor,
        fqdn=body.fqdn,
        port=body.port,
        tags=body.tags,
        notes=body.notes,
    )
    saved = await cmdb.update(updated)
    return {"ok": True, "device": saved.to_dict()}


@router.delete("/cmdb/devices/{device_id}")
async def delete_device(
    device_id: str,
    cmdb: FileCMDB = Depends(get_cmdb),
) -> dict[str, object]:
    deleted = await cmdb.delete(device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    return {"ok": True}
