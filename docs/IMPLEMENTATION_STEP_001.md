# Implementation Step 001

## Paso

Primera version ejecutable de `Nexus v1`.

## Objetivo

Pasar de estructura y documentacion a una superficie minima de software que ya se pueda ejecutar, probar y evolucionar.

## Que hago

1. Implemento `Nexus v1` como una capa nueva en `app/nexus/`.
2. Creo un coordinador central para chat, incidentes y monitorizacion.
3. Creo conectores minimos para `Alertmanager` y `Prometheus`.
4. Publico rutas nuevas HTTP bajo `/api/nexus`.
5. Conecto esas rutas a la app actual sin desmontar el runtime existente.
6. Añado tests unitarios y e2e de la nueva superficie.

## Que toco

### Integracion

- `app/main.py`
- `app/nexus/bootstrap.py`

### API Nexus v1

- `app/nexus/api/dependencies/auth.py`
- `app/nexus/api/routes/chat.py`
- `app/nexus/api/routes/health.py`
- `app/nexus/api/routes/incidents.py`
- `app/nexus/api/routes/monitoring.py`
- `app/nexus/api/schemas/chat.py`
- `app/nexus/api/schemas/incidents.py`
- `app/nexus/api/schemas/monitoring.py`

### Orquestacion y pipelines

- `app/nexus/orchestration/coordinator.py`
- `app/nexus/application/services/task_dispatcher.py`
- `app/nexus/application/use_cases/handle_alert.py`
- `app/nexus/incidents/incident_pipeline.py`
- `app/nexus/monitoring/alert_pipeline.py`

### Conectores

- `app/nexus/connectors/observability/alertmanager.py`
- `app/nexus/connectors/observability/prometheus.py`
- `app/nexus/connectors/runtime/desktop_bridge.py`

### Dominio y soporte

- `app/nexus/domain/entities/alert.py`
- `app/nexus/domain/entities/incident.py`
- `app/nexus/domain/entities/task.py`
- `app/nexus/domain/entities/tool_action.py`
- `app/nexus/domain/policies/risk.py`
- `app/nexus/execution/executor.py`
- `app/nexus/memory/operational_memory.py`
- `app/nexus/policy/guardrails.py`
- `app/nexus/workers/incident_worker.py`
- `app/nexus/workers/monitoring_worker.py`

### Tests

- `tests/unit/test_nexus_coordinator.py`
- `tests/e2e/test_nexus_v1_api.py`

## Resultado funcional

Queda disponible una primera superficie de `Nexus v1`:

- `GET /api/nexus/health`
- `POST /api/nexus/chat`
- `POST /api/nexus/incidents`
- `GET /api/nexus/monitoring/alerts`
- `POST /api/nexus/monitoring/query`
- `POST /api/nexus/monitoring/ingest`
- `POST /api/nexus/monitoring/silence`

## Problemas encontrados

### E2E inicial acoplado a `main.py`

El primer intento de test e2e importaba `main.py` y fallaba en este entorno por `redis.asyncio`.

### Solucion aplicada

Los tests e2e se desacoplaron del runtime viejo y ahora validan `Nexus v1` con una `FastAPI` minima registrada via `register_nexus_v1()`.

Esto prueba la nueva superficie sin depender de Redis, Mongo o del arranque completo heredado.

## Tests pasados

Comandos ejecutados:

```powershell
python -m pytest ..\tests\unit\test_nexus_coordinator.py -q
python -m pytest ..\tests\e2e\test_nexus_v1_api.py -q
```

Resultado:

- `6 passed` en unit
- `4 passed` en e2e

## Estado del paso

Completado.

La aplicacion ya tiene una primera version real de `Nexus v1` con:

- coordinador
- rutas nuevas
- monitorizacion basica
- ingestión de incidentes
- conectores iniciales
- tests verdes

## Siguiente paso recomendado

Mover la logica de monitorizacion real y el pipeline de incidentes del runtime antiguo al coordinador nuevo, empezando por `Alertmanager` y `Prometheus`.

