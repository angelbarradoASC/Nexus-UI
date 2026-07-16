# Resultado Bloque 2

## Objetivo

Dejar un entorno de desarrollo reproducible para Nexus Desktop sin tocar la UI protegida.

## Cambios aplicados

- `requirements-dev.txt`
  - corrige la referencia a dependencias de worker para usar `worker/requirements.txt`
- `scripts/bootstrap_dev.ps1`
  - crea o reutiliza `.venv`
  - instala dependencias de desarrollo
  - valida imports minimos: `fastapi`, `pytest`, `bson`, `paramiko`
- `scripts/test_contract.ps1`
  - ejecuta el contrato de UI
  - ejecuta `pytest -q`
  - persiste la salida en `runtime/logs/pytest-contract.log` para evitar perder trazas
- `docs/audit/COMANDOS_REPRODUCIBLES.md`
  - documenta bootstrap, verificacion y log de pytest

## Validaciones ejecutadas

### Bootstrap

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_dev.ps1
```

Resultado:

- `.venv` creada correctamente
- dependencias instaladas sin `ModuleNotFoundError`
- imports `fastapi`, `pytest`, `bson` y `paramiko` verificados

### Contrato de UI

```powershell
python scripts/audit/check_ui_contract.py
```

Resultado:

- `UI contract OK. Protected files verified: 125`

### Verificacion reproducible

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test_contract.ps1
```

Resultado:

- el script localiza correctamente `C:\DEV\Nexus-UI\.venv\Scripts\python.exe`
- el contrato UI pasa
- `pytest -q` reproduce fallos heredados en la suite global

## Fallos reproducidos

En la ejecucion reproducible aparecen fallos en:

- `tests/integration/test_worker.py::TestProcesarTareaFlujoFeliz::*`
- `tests/integration/test_worker.py::TestProcesarTareaPublicacionRedis::*`
- `tests/integration/test_worker.py::TestProcesarTareaExtraccionDatos::*`
- `tests/integration/test_worker.py::TestProcesarTareaErrores::test_error_en_publish_redis_no_rompe_flujo`

Estos fallos ya no son de bootstrap ni de dependencias: son fallos funcionales reproducibles de la suite.

## Garantias mantenidas

- no se han modificado ficheros UI protegidos
- no se han cambiado rutas, pantallas ni contratos visuales
- el entorno ya no depende de conocimiento tribal para instalar `bson` y `paramiko`

## Siguiente paso recomendado

No avanzar ocultando estos errores. La siguiente tarea debe atacar los fallos funcionales heredados o continuar con el bloque 3 solo si esta expresamente aceptado trabajar con esta deuda conocida.
