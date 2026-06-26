# Implementation Step 005

## Paso
Recepcion realista de alarmas en `Nexus v1` y preparacion de una bateria dockerizada para validar el flujo completo de alertas.

## Que hago
- Añado un endpoint de webhook para recibir lotes de `Alertmanager` en `Nexus`.
- Transformo alertas `firing` en incidentes normalizados de `Nexus`.
- Transformo alertas `resolved` en cierres de incidentes existentes cuando llega el mismo `fingerprint`.
- Mantengo compatibilidad con la ruta legacy configurada en `Alertmanager`: `/api/alerts/webhook`.
- Añado pruebas de integracion para el flujo:
  - webhook `firing`
  - creacion de incidente
  - webhook `resolved`
  - resolucion del incidente
  - auditoria resultante
- Creo una bateria de pruebas operativas en PowerShell para levantar el stack Docker, simular alertas, comprobar incidentes, silencios y auditoria.

## Que toco
- `app/nexus/api/schemas/monitoring.py`
- `app/nexus/orchestration/coordinator.py`
- `app/nexus/api/routes/monitoring.py`
- `app/main.py`
- `tests/unit/test_nexus_coordinator.py`
- `tests/e2e/test_nexus_v1_api.py`
- `tests/integration/test_nexus_alert_webhook_flow.py`
- `scripts/run_alert_battery.ps1`

## Resultado funcional
- `POST /api/nexus/monitoring/webhook`
- `POST /api/alerts/webhook`
- Conversión de alertas a incidentes
- Resolucion de incidentes por webhook
- Bateria dockerizada lista para:
  - levantar `mongodb`, `redis`, `web`, `alertmanager` y `prometheus`
  - disparar webhook directo
  - crear silencios
  - inyectar alertas en Alertmanager
  - validar auditoria e incidentes

## Tests que paso
- `python -m pytest tests\integration\test_nexus_alert_webhook_flow.py -q`
  - `1 passed`
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `13 passed`
- `python -m pytest tests\e2e\test_nexus_v1_api.py -q`
  - `6 passed`

## Validacion de Docker
- He intentado levantar el stack con:
  - `docker compose up -d mongodb redis web alertmanager prometheus`
- En este entorno no he podido ejecutar la bateria viva porque el daemon de Docker no estaba disponible:
  - error contra `//./pipe/dockerDesktopLinuxEngine`
- La bateria queda preparada en:
  - `scripts/run_alert_battery.ps1`
- En cuanto Docker Desktop o el daemon esten levantados, ese script ejecuta la validacion extremo a extremo.
