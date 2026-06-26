# IMPLEMENTATION_STEP_040

## Paso
Separacion del agente comercial de la home principal de Nexus y limpieza de previews de correo Thunderbird.

## Que he hecho
- He movido el bloque comercial de `nexus-v1` a una pantalla dedicada en `/nexus-sales`.
- He dejado la home principal enfocada en:
  - chat
  - estado de recoleccion
  - correo prioritario
  - actividad
- He creado una pantalla comercial separada con:
  - outreach
  - sincronizacion con CRM
  - actividad comercial
- He limpiado la extraccion del preview de correo para eliminar:
  - cabeceras MIME
  - residuos `quoted-printable`
  - boundaries tipo `enmime-*`
  - ruido de respuestas citadas

## Que he tocado
- `C:\DEV\Nexus-UI\app\nexus\mail\service.py`
- `C:\DEV\Nexus-UI\app\nexus\api\routes\ui.py`
- `C:\DEV\Nexus-UI\app\templates\nexus_v1.html`
- `C:\DEV\Nexus-UI\app\templates\nexus_sales.html`
- `C:\DEV\Nexus-UI\app\static\js\nexus_v1.js`
- `C:\DEV\Nexus-UI\app\static\js\nexus_sales.js`
- `C:\DEV\Nexus-UI\app\static\css\nexus_v1.css`
- `C:\DEV\Nexus-UI\tests\unit\test_thunderbird_mail_service.py`
- `C:\DEV\Nexus-UI\tests\e2e\test_nexus_v1_api.py`

## Que he probado
### Tests
```powershell
python -m pytest tests\unit\test_thunderbird_mail_service.py tests\e2e\test_nexus_v1_api.py -q
```

Resultado:
- `14 passed`

### Verificacion en navegador
He verificado con Selenium sobre la app viva en `http://127.0.0.1:5010`:

- En `/nexus-v1`
  - aparece `Thunderbird`
  - aparece el enlace `Comercial`
  - ya no aparece `Email outreach`
  - ya no aparece `CRM interno`

- En `/nexus-sales`
  - aparece `Email outreach`
  - aparece `CRM interno`
  - ya no aparece `Thunderbird`

## Como sigo
- revisar el prompt/salida del outreach para que el cuerpo del correo no huela a plantilla
- añadir acciones sobre correo prioritario para empujar un mensaje al CRM desde Nexus
- decidir si la pantalla comercial debe vivir tambien como workflow dentro de Open-Nexus desktop
