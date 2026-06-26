# IMPLEMENTATION STEP 036

## Paso
Compactación de `nexus-v1` y cambio de monitorización desde entorno local a servidor remoto.

## Qué hice
- Apreté la interfaz de `nexus-v1` para reducir aire muerto:
  - menos ancho máximo
  - topbar más compacta
  - rail derecho más estrecho
  - timeline de chat con altura más contenida
  - formularios y tarjetas laterales más densos
- Cambié la configuración por defecto y el `.env` para que Prometheus y Alertmanager dejen de apuntar a contenedores locales y miren al servidor remoto `192.168.1.150`.
- Añadí `Grafana` como tercera fuente visible en el estado de recolección.
- Ajusté el render del estado para distinguir `up`, `degraded` y `down`.
- Arreglé una circular real entre `desktop.storage.local_state` y `desktop.opennexus.engine` que impedía arrancar la app web completa al reiniciar.

## Qué toqué
- `app/config.py`
- `.env`
- `app/nexus/connectors/observability/grafana.py`
- `app/nexus/api/dependencies/auth.py`
- `app/nexus/orchestration/coordinator.py`
- `app/templates/nexus_v1.html`
- `app/static/css/nexus_v1.css`
- `app/static/js/nexus_v1.js`
- `desktop/storage/local_state.py`
- `desktop/opennexus/__init__.py`
- `tests/unit/test_nexus_coordinator.py`
- `tests/integration/test_nexus_alert_webhook_flow.py`
- `tests/e2e/test_nexus_v1_api.py`

## Diagnóstico remoto
- `Prometheus` está arriba en `http://192.168.1.150:9090`
- `Grafana` está arriba en `http://192.168.1.150:3000`
- `Alertmanager` no aparece desplegado en `http://192.168.1.150:9093`
- Resultado: la UI ahora refleja esa realidad en vez de mirar a endpoints locales falsos

## Tests pasados
```powershell
python -m pytest tests\unit\test_open_nexus_engine.py tests\unit\test_desktop_runtime.py tests\unit\test_nexus_coordinator.py tests\e2e\test_nexus_v1_api.py -q
python -m pytest tests\unit\test_nexus_coordinator.py tests\integration\test_nexus_alert_webhook_flow.py tests\e2e\test_nexus_v1_api.py -q
```

Resultados:
- `40 passed`
- `27 passed`

## Validación manual
- Reinicié la app local
- Verifiqué `GET /api/nexus/monitoring/collectors`
- Respuesta actual:
  - `Prometheus: up`
  - `Alertmanager: down`
  - `Grafana: up`
