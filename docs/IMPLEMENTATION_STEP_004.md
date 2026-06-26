# Implementation Step 004

## Paso
Ampliacion operativa de `Nexus v1` para gestionar el ciclo de vida de incidentes y permitir acciones de runbook en modo controlado.

## Que hago
- Añado detalle individual de incidente para poder consultar una incidencia concreta por ID.
- Añado actualizacion de estado de incidente para pasar de `open` a estados como `acknowledged` o `resolved`.
- Añado ejecucion o previsualizacion de acciones ligadas al runbook de un incidente.
- Refuerzo el modelo de incidente con `owner` y `resolution_note`.
- Amplio los repositorios de incidentes para soportar `get` y `update`, tanto en memoria como con adaptador MongoDB.
- Hago que `health` exponga workers operativos reales mediante un registro de workers.
- Mejoro la UI de `/nexus-v1` para poder:
  - hacer `acknowledge`
  - resolver incidentes
  - lanzar acciones de runbook en `dry-run`

## Que toco
- `app/nexus/domain/entities/incident.py`
- `app/nexus/incidents/repository.py`
- `app/nexus/api/schemas/incidents.py`
- `app/nexus/orchestration/coordinator.py`
- `app/nexus/api/routes/incidents.py`
- `app/nexus/workers/incident_worker.py`
- `app/nexus/workers/monitoring_worker.py`
- `app/nexus/workers/registry.py`
- `app/static/js/nexus_v1.js`
- `app/static/css/nexus_v1.css`
- `tests/unit/test_nexus_coordinator.py`
- `tests/e2e/test_nexus_v1_api.py`

## Resultado funcional
- `GET /api/nexus/incidents/{incident_id}`
- `PATCH /api/nexus/incidents/{incident_id}`
- `POST /api/nexus/incidents/{incident_id}/actions`
- `health` con workers visibles
- UI con botones de operacion sobre incidentes

## Tests que paso
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `12 passed`
- `python -m pytest tests\e2e\test_nexus_v1_api.py -q`
  - `6 passed`

## Notas
- Las acciones de runbook respetan el catalogo de `auto_actions`. Si una accion no esta permitida por el runbook, `Nexus` la bloquea y la audita.
- La UI ejecuta acciones de runbook en `dry-run` para mantener el comportamiento seguro durante esta fase.
