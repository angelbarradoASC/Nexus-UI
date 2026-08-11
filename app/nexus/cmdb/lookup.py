"""
app/nexus/cmdb/lookup.py
---------------------------
Búsqueda de texto libre sobre el CMDB, compartida por cualquier agente que
necesite resolver un dispositivo a partir de lo que dice el usuario (nombre,
IP, tipo, vendor, notas, tags). Extraído de SystemTaskAgent para que
RemoteOpsAgent lo reutilice sin duplicar la lógica.
"""

from __future__ import annotations

from nexus.cmdb.source import CMDBSource


async def search_devices(cmdb: CMDBSource, query: str, *, limit: int = 5) -> str:
    """Busca dispositivos por texto libre. Devuelve un resumen legible por un LLM."""
    if cmdb is None:
        return "CMDB no disponible."

    needle = (query or "").strip().lower()
    if not needle:
        return "Consulta vacia."

    try:
        devices = await cmdb.list_devices(enabled_only=False)
    except Exception:
        return "Error consultando el CMDB."

    hits: list[str] = []
    for d in devices:
        haystack = " ".join(
            str(v) for v in (d.name, d.ip, d.type, d.vendor, d.notes, d.fqdn) if v
        ).lower()
        haystack += " " + " ".join(f"{k}:{v}" for k, v in (d.tags or {}).items()).lower()
        if needle in haystack:
            hits.append(
                f"{d.name} (device_id={d.device_id}, ip={d.ip}, tipo={d.type}, "
                f"protocolo={d.management_protocol}, notas={d.notes or '-'})"
            )

    if not hits:
        return f"No hay ningun dispositivo en el CMDB que coincida con '{query}'."
    return "Encontrado en el CMDB:\n" + "\n".join(hits[:limit])
