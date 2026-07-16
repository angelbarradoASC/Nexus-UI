# Resultado Bloque 4

## Objetivo

Mover secretos del proveedor desktop a almacenamiento seguro sin cambiar la experiencia visual de Configuracion.

## Archivos tocados

- `desktop/requirements.txt`
- `desktop/storage/provider_config.py`
- `desktop/storage/local_state.py`
- `app/nexus/security/__init__.py`
- `app/nexus/security/desktop_secret_store.py`
- `tests/unit/test_desktop_provider_secrets.py`
- `tests/unit/test_desktop_runtime.py`
- `tests/unit/test_local_state_atomic.py`
- `tests/unit/test_audit_tanda1_contract.py`
- `tests/smoke/test_smoke_desktop.py`
- `docs/audit/DESKTOP_SECRETS_MIGRATION.md`

## Cambios aplicados

- se anade `keyring` a dependencias desktop
- el secreto del proveedor ya no se persiste en claro en `llm_provider.json`
- el JSON usa `credential_ref` como referencia no secreta
- el guardado y la lectura migran automaticamente JSON antiguos con `api_key`
- la migracion crea backup previo `llm_provider.pre-secrets-migration-*.json`
- los errores del vault del sistema no filtran secretos
- los endpoints desktop mantienen el mismo contrato funcional y siguen devolviendo la clave enmascarada

## Tests ejecutados

### Suite focal de desktop y secretos

```powershell
C:\DEV\Nexus-UI\.venv\Scripts\python.exe -m pytest -q tests\unit\test_desktop_provider_secrets.py tests\unit\test_desktop_runtime.py tests\unit\test_local_state_atomic.py tests\unit\test_audit_tanda1_contract.py tests\smoke\test_smoke_desktop.py -k "provider or desktop or secret or settings"
```

Resultado resumido:

- `33 passed, 2 deselected, 1 warning`

### Contrato de UI

```powershell
python scripts/audit/check_ui_contract.py
```

Resultado:

- `UI contract OK. Protected files verified: 125`

### Dependencia del almacen seguro

```powershell
C:\DEV\Nexus-UI\.venv\Scripts\python.exe -m pip install keyring==25.2.1
```

Resultado:

- instalacion completada correctamente en el `.venv`

## Hash UI antes y despues

- antes: `125` ficheros protegidos verificados
- despues: `125` ficheros protegidos verificados

## Riesgos abiertos

- no se ha cambiado la UI, pero la disponibilidad efectiva del almacen seguro en cada equipo sigue dependiendo del backend real de Windows Credential Manager
- el resto de deuda heredada de la suite global sigue fuera de este bloque

## Rollback exacto

1. Parar Nexus Desktop.
2. Restaurar `llm_provider.pre-secrets-migration-*.json` si hiciera falta volver al estado previo.
3. Revisar o limpiar la entrada del almacen seguro asociada a:
   - `nexus.desktop.provider.openai_compatible.primary`
4. Reiniciar Nexus Desktop.

## Commit y base

- base SHA de trabajo: `2d8e085fcac8803974ee82181c54fe77009f1e8f`
- commit de esta tarea: no creado en esta sesion
