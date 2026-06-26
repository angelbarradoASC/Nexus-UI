"""
app/nexus/cmdb/models.py
--------------------------
Modelo canónico de dispositivo para el CMDB de NEXUS.

Diseñado para ser consumido por cualquier fuente:
  - FileCMDB (JSON local)
  - MonBombCMDB (API REST cuando esté disponible)
  - NetBoxCMDB (si el cliente ya tiene NetBox)

Nunca contiene credenciales — esas viven en VaultService.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Device:
    device_id:           str
    name:                str
    ip:                  str
    type:                str          # server | switch | router | firewall | windows | appliance | unknown
    management_protocol: str          # ssh | winrm | rest_api | snmp | none
    os:                  str = ""     # linux | windows | ios | junos | eos | fortigate | panos | ...
    vendor:              str = ""     # cisco | juniper | arista | hp | paloalto | fortinet | generic
    fqdn:                str | None = None
    port:                int = 22
    tags:                dict[str, Any] = field(default_factory=dict)
    discovery_source:    str = "manual"   # manual | monbomb | netbox | import
    enabled:             bool = True
    notes:               str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Device":
        known = {f.name for f in Device.__dataclass_fields__.values()}
        return Device(**{k: v for k, v in data.items() if k in known})
