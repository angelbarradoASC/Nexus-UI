# Implementation Step 041

## Objetivo

Introducir `MunicipalProspector` en `Sales` como flujo principal de prospeccion activa, dejando CSV/outreach como via secundaria.

## Cambios principales

- nueva configuracion de prospeccion en `app/config.py`
- ampliacion del conector CRM en `app/nexus/connectors/crm/assets.py`
- nuevo paquete `app/nexus/prospecting/`
  - `service.py`
  - `repository.py`
  - `__init__.py`
- nueva API:
  - `app/nexus/api/routes/prospecting.py`
  - `app/nexus/api/schemas/prospecting.py`
- runtime actualizado en:
  - `app/nexus/api/dependencies/auth.py`
  - `app/nexus/bootstrap.py`
- nueva superficie `Sales` centrada en prospeccion:
  - `app/templates/nexus_sales.html`
  - `app/static/js/nexus_sales.js`
  - `app/static/css/nexus_v1.css`

## Comportamiento nuevo

- lanzar runs de prospeccion municipal por zona/radio/tipo
- persistir runs y resultados
- puntuar resultados
- deduplicar contra CRM por dominio/email/nombre/telefono
- preparar `push to CRM` por resultado o por run
- mostrar resultados y evidencia en la pantalla `Sales`

## Tests

Ejecutado:

```powershell
python -m py_compile C:\DEV\Nexus-UI\app\nexus\prospecting\service.py C:\DEV\Nexus-UI\app\nexus\prospecting\repository.py C:\DEV\Nexus-UI\app\nexus\api\routes\prospecting.py C:\DEV\Nexus-UI\app\nexus\api\schemas\prospecting.py
python -m pytest tests\unit\test_municipal_prospecting_service.py tests\e2e\test_nexus_v1_api.py -q
```

Resultado:

- `14 passed`

## Observaciones

Esto ya no es solo UI. El flujo funcional existe y persiste datos, pero sigue siendo una primera version:

- usa discovery basada en OSM/Overpass
- usa validacion DNS/MX
- no hace scraping agresivo
- no mete todavia SMTP probe
- el `push` a CRM arranca en preview seguro desde UI
