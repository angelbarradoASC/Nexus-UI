"""
app/nexus/api/routes/vault.py
-------------------------------
Endpoints del Vault de credenciales.

Reglas de seguridad de esta API:
  - Las credenciales (passwords, SSH keys) NUNCA se devuelven en GET.
  - Los endpoints de escritura solo funcionan con el vault desbloqueado.
  - El test de conexión devuelve ok/message, nunca credenciales ni outputs sensibles.
  - El unlock/setup reciben la master_password por POST body (HTTPS en producción).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nexus.api.dependencies.auth import get_vault, get_access_service
from nexus.access.service import AgentAccessService
from nexus.vault.service import VaultService

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class VaultSetupRequest(BaseModel):
    master_password: str

class VaultUnlockRequest(BaseModel):
    master_password: str

class StoreCredentialRequest(BaseModel):
    auth_method: str = "password"   # password | ssh_key | api_token
    username:    str
    secret:      str = ""           # password o API token
    ssh_key:     str | None = None  # PEM key completo


# ── Estado del vault ──────────────────────────────────────────────────────────

@router.get("/vault/status")
async def vault_status(vault: VaultService = Depends(get_vault)) -> dict[str, object]:
    return {
        "initialized": vault.is_initialized,
        "locked":      vault.is_locked,
    }


@router.post("/vault/setup")
async def vault_setup(
    body: VaultSetupRequest,
    vault: VaultService = Depends(get_vault),
) -> dict[str, object]:
    """Primera vez: establece la master password."""
    if vault.is_initialized:
        raise HTTPException(status_code=409, detail="El vault ya está inicializado")
    await vault.setup(body.master_password)
    return {"ok": True, "message": "Vault inicializado correctamente"}


@router.post("/vault/unlock")
async def vault_unlock(
    body: VaultUnlockRequest,
    vault: VaultService = Depends(get_vault),
) -> dict[str, object]:
    if not vault.is_initialized:
        raise HTTPException(status_code=400, detail="El vault no está inicializado. Usa /vault/setup primero")
    success = await vault.unlock(body.master_password)
    if not success:
        raise HTTPException(status_code=401, detail="Contraseña maestra incorrecta")
    return {"ok": True, "message": "Vault desbloqueado"}


@router.post("/vault/lock")
async def vault_lock(vault: VaultService = Depends(get_vault)) -> dict[str, object]:
    vault.lock()
    return {"ok": True, "message": "Vault bloqueado"}


# ── Credenciales ──────────────────────────────────────────────────────────────

@router.get("/vault/credentials")
async def list_credentials(
    vault: VaultService = Depends(get_vault),
) -> dict[str, object]:
    """Metadatos de credenciales sin descifrar. Nunca expone secrets."""
    if vault.is_locked:
        raise HTTPException(status_code=423, detail="El vault está bloqueado")
    stubs = await vault.list_credential_stubs()
    return {"total": len(stubs), "credentials": stubs}


@router.post("/vault/credentials/{device_id}")
async def store_credential(
    device_id: str,
    body: StoreCredentialRequest,
    vault: VaultService = Depends(get_vault),
) -> dict[str, object]:
    """Guarda o reemplaza credenciales para un dispositivo."""
    if vault.is_locked:
        raise HTTPException(status_code=423, detail="El vault está bloqueado")
    cred = await vault.store(
        device_id=device_id,
        auth_method=body.auth_method,
        username=body.username,
        secret=body.secret,
        ssh_key=body.ssh_key,
    )
    return {"ok": True, "cred_id": cred.cred_id, "device_id": cred.device_id}


@router.delete("/vault/credentials/{device_id}")
async def delete_credential(
    device_id: str,
    vault: VaultService = Depends(get_vault),
) -> dict[str, object]:
    if vault.is_locked:
        raise HTTPException(status_code=423, detail="El vault está bloqueado")
    deleted = await vault.delete_credential(device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credencial no encontrada")
    return {"ok": True}


# ── Test de conexión ──────────────────────────────────────────────────────────

@router.post("/vault/test/{device_id}")
async def test_connection(
    device_id: str,
    access: AgentAccessService = Depends(get_access_service),
) -> dict[str, object]:
    """
    Intenta conectar al dispositivo y ejecuta 'echo nexus-ok'.
    Devuelve ok/message. Nunca devuelve credenciales ni output sensible.
    """
    return await access.test_connection(device_id)
