# Resultado Bloque 3

## Objetivo

Endurecer la migracion desde JSON y JSONL a SQLite para prospecting y outreach sin tocar UI, rutas expuestas ni payloads funcionales.

## Archivos tocados

- `app/nexus/persistence/json_migration.py`
- `app/nexus/persistence/prospecting_schema.py`
- `app/nexus/persistence/outreach_schema.py`
- `app/nexus/prospecting/repository.py`
- `app/nexus/outreach/repository.py`
- `app/nexus/storage/json_files.py`
- `tests/unit/test_prospecting_repository_sqlite.py`
- `tests/unit/test_outreach_repository_sqlite.py`
- `tests/integration/test_prospecting_outreach_migration.py`
- `docs/audit/SQLITE_MIGRATION_CONTRACT.md`

## Cambios aplicados

- se anade la tabla `storage_migrations` en las bases SQLite de prospecting y outreach
- cada origen legado registra `source_path`, `source_hash`, fecha, resultado y numero de registros
- la migracion crea backups fechados antes de importar
- el mismo hash legado no se reimporta
- duplicados de `run_id` y `event_id` fuerzan rollback completo
- si ya existia un SQLite poblado anterior a este contrato, el estado se adopta y se registra sin reimportar
- se habilita rollback temporal al backend legado mediante:
  - `NEXUS_PROSPECTING_STORAGE_BACKEND=json`
  - `NEXUS_OUTREACH_STORAGE_BACKEND=json`

## Tests ejecutados

### Focalizados de migracion

```powershell
C:\DEV\Nexus-UI\.venv\Scripts\python.exe -m pytest -q tests\unit\test_prospecting_repository_sqlite.py tests\unit\test_outreach_repository_sqlite.py tests\integration\test_prospecting_outreach_migration.py
```

Resultado resumido:

- `13 passed, 1 warning`

### Endpoints afectados por el cambio

```powershell
C:\DEV\Nexus-UI\.venv\Scripts\python.exe -m pytest -q tests\e2e\test_nexus_v1_api.py -k "outreach_endpoints or prospecting_endpoints"
```

Resultado resumido:

- `2 passed, 1 warning`

### Subconjunto amplio del bloque 3

```powershell
C:\DEV\Nexus-UI\.venv\Scripts\python.exe -m pytest -q tests -k "sqlite or migration or prospecting or outreach"
```

Resultado resumido:

- `33 passed, 543 deselected, 1 warning`

### Contrato de UI

```powershell
python scripts/audit/check_ui_contract.py
```

Resultado:

- `UI contract OK. Protected files verified: 125`

## Hash UI antes y despues

- antes: `125` ficheros protegidos verificados
- despues: `125` ficheros protegidos verificados

## Riesgos abiertos

- la suite global `pytest -q` completa sigue teniendo deuda heredada fuera de este bloque, especialmente en `tests/integration/test_worker.py`
- queda pendiente el bloque 4 de secretos desktop; este bloque solo cubre persistencia y rollback de prospecting/outreach

## Rollback exacto

1. Parar Nexus Desktop.
2. Restaurar el backup fechado correspondiente:
   - `prospecting_runs.migrated-backup-*.json`
   - `campaigns.migrated-backup-*.json`
   - `events.migrated-backup-*.jsonl`
   - `outreach_prompt.migrated-backup-*.txt`
3. Activar temporalmente:
   - `NEXUS_PROSPECTING_STORAGE_BACKEND=json`
   - `NEXUS_OUTREACH_STORAGE_BACKEND=json`
4. Reiniciar Nexus.

## Commit y base

- base SHA de trabajo: `2d8e085fcac8803974ee82181c54fe77009f1e8f`
- commit de esta tarea: no creado en esta sesion
