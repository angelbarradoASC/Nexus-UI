# SQLite Migration Contract

## Objetivo

Endurecer la migracion desde JSON y JSONL a SQLite sin tocar payloads, rutas expuestas ni UI.

## Garantias

- Antes de migrar se crea un backup fechado del origen legado.
- Cada origen legado registra su `source_path`, `source_hash`, fecha, resultado y numero de registros en `storage_migrations`.
- Si el mismo hash ya fue migrado con exito, la migracion no se repite.
- Si ocurre una excepcion durante la importacion, la transaccion SQLite hace rollback completo y la migracion queda registrada como fallo.
- `run_id`, `campaign_id` y `event_id` siguen protegidos por claves primarias.
- SQLite mantiene `WAL`, `foreign_keys=ON`, `busy_timeout=5000` y transacciones `BEGIN IMMEDIATE`.

## Rollback operativo

1. Parar Nexus Desktop.
2. Restaurar el backup fechado del JSON o JSONL legado si fuera necesario.
3. Activar temporalmente el backend legado:
   - `NEXUS_PROSPECTING_STORAGE_BACKEND=json`
   - `NEXUS_OUTREACH_STORAGE_BACKEND=json`
4. Reiniciar Nexus.

Este rollback no cambia la UI. Solo conmuta internamente el repositorio persistente.
