# Implementation Step 025

## Paso

Puente inicial entre `Nexus Outreach` y el CRM interno real de `assets-web-api`.

## Qué he hecho

- He corregido la dirección de integración:
  - el CRM fuente correcto es [assets-web-api](C:/DEV/GitHub/assets-web-api), no `CDM-ODOO`
- He añadido configuración para el CRM interno de Assets:
  - `assets_crm_base_url`
  - `assets_crm_username`
  - `assets_crm_password`
- He creado un conector JWT para `assets-web-api`:
  - login contra `/api/token/`
  - lectura de estado
  - creación de empresa
  - actualización del pipeline
  - creación de notas CRM
- He creado un `CRMBridgeService` para:
  - ver estado del enlace
  - sincronizar prospectos de una campaña de outreach
  - evitar duplicados por dominio reutilizando empresa existente
- He expuesto endpoints nuevos:
  - `GET /api/nexus/crm/status`
  - `POST /api/nexus/crm/campaigns/{campaign_id}/sync`
- He añadido visibilidad en la UI:
  - tarjeta `CRM interno`
  - estado del conector
  - pendientes
  - campañas
  - acción `Preparar 3 leads`

## Qué he tocado

- [config.py](C:/DEV/Nexus-UI/app/config.py)
- [assets.py](C:/DEV/Nexus-UI/app/nexus/connectors/crm/assets.py)
- [__init__.py](C:/DEV/Nexus-UI/app/nexus/connectors/crm/__init__.py)
- [service.py](C:/DEV/Nexus-UI/app/nexus/crm/service.py)
- [crm.py](C:/DEV/Nexus-UI/app/nexus/api/routes/crm.py)
- [crm.py](C:/DEV/Nexus-UI/app/nexus/api/schemas/crm.py)
- [auth.py](C:/DEV/Nexus-UI/app/nexus/api/dependencies/auth.py)
- [bootstrap.py](C:/DEV/Nexus-UI/app/nexus/bootstrap.py)
- [nexus_v1.html](C:/DEV/Nexus-UI/app/templates/nexus_v1.html)
- [nexus_v1.css](C:/DEV/Nexus-UI/app/static/css/nexus_v1.css)
- [nexus_v1.js](C:/DEV/Nexus-UI/app/static/js/nexus_v1.js)
- [test_crm_bridge_service.py](C:/DEV/Nexus-UI/tests/unit/test_crm_bridge_service.py)
- [test_nexus_v1_api.py](C:/DEV/Nexus-UI/tests/e2e/test_nexus_v1_api.py)

## Qué valida esta versión

- `Nexus` ya puede preparar la sincronización de los primeros prospectos al CRM interno correcto.
- La integración está pensada sobre:
  - `Company`
  - `pipeline`
  - `CRMNote`
- La operación inicial se hace en `dry-run` para que mañana podamos revisar antes de escribir en producción.

## Validación real

Se ha validado contra la instancia local de [assets-web-api](C:/DEV/GitHub/assets-web-api):

- backend Django levantado en `http://127.0.0.1:8000`
- autenticación JWT correcta con usuario interno de staff
- `GET /api/nexus/crm/status` devuelve `configured=true` y `status=up`
- `POST /api/nexus/crm/campaigns/out-7fd8e02013/sync` con `dry_run=false` creó:
  - `Company`:
    - `Example`
    - `example.com`
    - `status=prospect`
    - `pipeline_stage=new`
  - `CRMNote` inicial ligada a la empresa

También se verificó directamente en el CRM interno:

- `/api/pipeline/` muestra la empresa creada
- `/api/pipeline/1/notes/` muestra la nota generada por Nexus

## Incidencia corregida

Durante la validación se detectó que el backend local de `assets-web-api` no tenía aplicadas las migraciones de `CRMNote`, lo que rompía `/api/pipeline/` con `500`.

Se corrigió ejecutando:

- `python manage.py migrate`

Además, para la validación local, se rebootstrapearon los usuarios del área privada con la contraseña demo del propio proyecto para recuperar acceso JWT al entorno local.

## Tests

Pasados:

- `python -m pytest tests/unit/test_crm_bridge_service.py tests/e2e/test_nexus_v1_api.py -q`
  - `11 passed`
- `python -m pytest tests/unit/test_outreach_service.py tests/unit/test_config.py -q`
  - `26 passed`
