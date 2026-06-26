# Implementation Step 006

## Paso
Rediseño de la superficie principal de `Nexus v1` para que se comporte como una consola operativa y no como un panel técnico.

## Que hago
- Cambio la pantalla de `Nexus v1` a un layout de tres columnas:
  - izquierda `20%`: historial del usuario
  - centro `50%`: chat general
  - derecha `30%`: actividad automatica y alarmas procesadas
- Añado una banda superior de estado de recoleccion con bullets verdes o rojos para cada medio integrado.
- Defino un endpoint nuevo para estado de recolectores y sistemas de alarmas integrados.
- Hago que la UI solo haga polling periodico del estado de recolectores, como base de disponibilidad operativa.
- Reaprovecho auditoria e incidentes para poblar:
  - historial del usuario
  - actividad automatica
- Enriquecimiento del audit de chat con `message_preview` para que el historial sea legible.

## Que toco
- `app/nexus/connectors/observability/alertmanager.py`
- `app/nexus/connectors/observability/prometheus.py`
- `app/nexus/orchestration/coordinator.py`
- `app/nexus/api/routes/monitoring.py`
- `app/templates/nexus_v1.html`
- `app/static/css/nexus_v1.css`
- `app/static/js/nexus_v1.js`
- `tests/unit/test_nexus_coordinator.py`
- `tests/e2e/test_nexus_v1_api.py`

## Resultado funcional
- `GET /api/nexus/monitoring/collectors`
- Pantalla principal con:
  - estado de recolectores arriba
  - historial del usuario a la izquierda
  - chat general en el centro
  - actividad automatica a la derecha
- Polling solo para estado de recolectores

## Tests que paso
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `14 passed`
- `python -m pytest tests\e2e\test_nexus_v1_api.py -q`
  - `6 passed`

## Notas
- Los medios que aparecen arriba son los realmente integrados en esta version:
  - `Prometheus`
  - `Alertmanager`
- `Zabbix` no aparece todavia porque aun no hay integracion implementada en esta base.
