# Desktop Secrets Migration

## Objetivo

Mover el secreto del proveedor LLM desktop fuera de `llm_provider.json` sin cambiar la pantalla de Configuracion ni el contrato visible de los endpoints desktop.

## Comportamiento

- El fichero `%LOCALAPPDATA%\Open-Nexus\config\llm_provider.json` conserva solo datos no secretos.
- La API key se guarda en el almacen seguro del sistema via `keyring`.
- El JSON persistido usa `credential_ref` como referencia estable no secreta.
- `GET /api/desktop/providers` y `PUT /api/desktop/providers` mantienen la misma superficie funcional y siguen devolviendo la clave enmascarada.

## Migracion

Cuando se detecta un JSON antiguo con `api_key` en claro:

1. se guarda la clave en el almacen seguro
2. se crea backup del JSON legado:
   - `llm_provider.pre-secrets-migration-<timestamp>.json`
3. se reescribe `llm_provider.json` con:
   - `credential_ref`
   - `api_key` vacia

## Error handling

- Si el almacen seguro falla, no se escribe un JSON nuevo inconsistente.
- Los errores propagados no incluyen el valor del secreto.
- Un JSON sin secreto sigue funcionando.

## Forma persistida esperada

```json
{
  "provider_type": "openai_compatible",
  "provider_label": "Servidor remoto",
  "api_base_url": "https://example.invalid/v1",
  "api_key": "",
  "credential_ref": "nexus.desktop.provider.openai_compatible.primary",
  "model": "gpt-4o-mini",
  "enabled": true,
  "updated_at": "2026-06-23T16:00:00+00:00"
}
```

## Rollback operativo

1. Parar Nexus Desktop.
2. Restaurar el backup `llm_provider.pre-secrets-migration-*.json` si fuera necesario.
3. Si hay que volver temporalmente al modo legado para inspeccion manual, restaurar el JSON backup y volver a guardar desde desktop despues de revisar el almacen seguro.

No se cambia UI para ejecutar este rollback.
