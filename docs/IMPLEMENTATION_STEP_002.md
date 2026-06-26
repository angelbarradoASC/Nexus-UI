# Implementation Step 002

## Paso

Primera superficie web revisable de `Nexus v1`.

## Objetivo

Tener una version funcional que podamos abrir en navegador y revisar juntos, sin depender de inspeccionar solo APIs o tests.

## Que hago

1. Añado una pagina de trabajo para `Nexus v1`.
2. La conecto a las rutas nuevas ya creadas.
3. Mantengo el runtime actual intacto y monto la vista sobre la capa nueva.
4. Añado test e2e para asegurar que la pagina carga.

## Que toco

### Rutas

- `app/nexus/bootstrap.py`
- `app/nexus/api/routes/ui.py`

### UI

- `app/templates/nexus_v1.html`
- `app/static/css/nexus_v1.css`
- `app/static/js/nexus_v1.js`

### Tests

- `tests/e2e/test_nexus_v1_api.py`

## Resultado funcional

Queda disponible una pagina nueva en:

- `/nexus-v1`

La pagina permite:

- ver el estado de `Nexus v1`
- probar el flujo de chat
- abrir un incidente manual
- leer alertas
- consultar Prometheus
- crear silencios en Alertmanager

## Enfoque

No he intentado hacer una UI final ni bonita de producto cerrado.
He montado una superficie de trabajo clara para validar funcionalidad y revisar comportamiento juntos.

## Tests pasados

Comandos ejecutados:

```powershell
python -m pytest ..\tests\unit\test_nexus_coordinator.py -q
python -m pytest ..\tests\e2e\test_nexus_v1_api.py -q
```

Resultado:

- `6 passed` en unit
- `5 passed` en e2e

## Estado del paso

Completado.

Ahora ya tenemos:

- backend minimo funcional
- rutas nuevas activas
- superficie web para revisar
- tests verdes sobre la capa nueva

## Siguiente paso recomendado

Hacer que la pagina no sea solo de demo y empezar a colgarle comportamiento real:

- ingestión real de alertas
- listado enriquecido de incidentes
- runbooks y diagnostico operativo

