"""
app/nexus/vault/check.py
---------------------------
Comprobacion de credenciales en el Vault para un device_id, compartida por
cualquier agente que necesite saber si existen SIN revelar el secreto.
Extraido de RemoteOpsAgent para que SelfConfigAgent lo reutilice sin duplicar
logica (mismo motivo que app/nexus/cmdb/lookup.py).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("nexus.vault.check")


async def check_credentials(vault, device_id: str) -> str:
    """Devuelve un resumen legible por un LLM. Nunca incluye el secreto."""
    if vault is None:
        return "Vault no disponible."
    if not device_id:
        return "Falta el device_id."
    if vault.is_locked:
        return "El Vault esta bloqueado. Pide al usuario que lo desbloquee desde la pestana Vault antes de continuar."
    try:
        credential = await vault.get_credential(device_id)
    except Exception:
        logger.exception("Fallo consultando el Vault")
        return "Error consultando el Vault."
    if credential is None:
        return f"No hay credenciales guardadas en el Vault para {device_id}. Hay que anadirlas antes de poder conectar."
    return f"Hay credenciales para {device_id}: usuario={credential.username}, metodo={credential.auth_method}."
