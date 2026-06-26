# Implementation Step 003

## Paso
Primera entrega operativa ampliada de `Nexus v1` con persistencia de incidentes, auditoria, runbooks, politicas de ejecucion, mejora de UI y endurecimiento basico del runtime.

## Que hago
- Amplio el coordinador central para que `Nexus` no solo responda, sino que persista incidentes, registre auditoria y enriquezca alertas con runbooks y decisiones operativas.
- Añado repositorios en memoria y preparados para MongoDB para incidentes y auditoria.
- Expongo nuevas rutas para consultar incidentes, runbooks y auditoria reciente.
- Mejoro la pantalla `/nexus-v1` para ver historial operativo en tarjetas, en lugar de depender solo de bloques JSON.
- Introduzco politica simple de riesgo para decidir si una accion puede ser automatica y si debe crear ticket.
- Dejo conectores base para `Jira` y `ServiceNow`, con comportamiento seguro cuando no estan configurados.
- Ajusto el montaje de templates y static para que funcione tanto en la app principal como en tests aislados.

## Que toco
- `app/config.py`
- `app/main.py`
- `app/nexus/api/dependencies/auth.py`
- `app/nexus/api/routes/audit.py`
- `app/nexus/api/routes/incidents.py`
- `app/nexus/api/routes/monitoring.py`
- `app/nexus/api/routes/ui.py`
- `app/nexus/api/schemas/incidents.py`
- `app/nexus/api/schemas/monitoring.py`
- `app/nexus/audit/models.py`
- `app/nexus/audit/repository.py`
- `app/nexus/bootstrap.py`
- `app/nexus/connectors/itsm/jira.py`
- `app/nexus/connectors/itsm/servicenow.py`
- `app/nexus/connectors/observability/alertmanager.py`
- `app/nexus/connectors/observability/prometheus.py`
- `app/nexus/domain/entities/incident.py`
- `app/nexus/incidents/incident_pipeline.py`
- `app/nexus/incidents/repository.py`
- `app/nexus/monitoring/alert_pipeline.py`
- `app/nexus/monitoring/runbooks.py`
- `app/nexus/orchestration/coordinator.py`
- `app/nexus/policy/guardrails.py`
- `app/static/css/nexus_v1.css`
- `app/static/js/nexus_v1.js`
- `app/templates/nexus_v1.html`
- `tests/e2e/test_nexus_v1_api.py`
- `tests/unit/test_nexus_coordinator.py`

## Resultado funcional
- `GET /api/nexus/incidents`
- `GET /api/nexus/audit`
- `GET /api/nexus/monitoring/runbooks`
- Persistencia de incidentes en memoria y adaptador listo para MongoDB
- Auditoria operativa persistida
- Enriquecimiento de alertas con runbooks
- Politica basica de ejecucion y ticketing
- UI con historial de incidentes, runbooks y auditoria
- Montaje robusto de templates y static para revision en local y en test

## Tests que paso
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `9 passed`
- `python -m pytest tests\e2e\test_nexus_v1_api.py -q`
  - `5 passed`

## Notas
- El proyecto no esta inicializado como repositorio Git en este entorno, asi que la trazabilidad de archivos tocados se ha documentado manualmente en este paso.
- `Jira` y `ServiceNow` quedan en modo seguro si no hay credenciales reales: no bloquean el flujo y devuelven respuesta simulada o `not_configured`.
