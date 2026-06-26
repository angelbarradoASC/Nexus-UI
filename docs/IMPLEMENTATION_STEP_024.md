# Implementation Step 024

## Paso

Integracion de correo desde Thunderbird para:

- descubrir cuentas reales desde el perfil local
- leer dos cuentas IMAP gestionadas por Thunderbird
- cualificar mensajes importantes
- mostrar una bandeja priorizada en la UI de Nexus

## Que hice

1. Añadi configuracion de Thunderbird en `AppConfig`.
2. Cree un `ThunderbirdMailManager` que:
   - resuelve el perfil activo
   - parsea `prefs.js`
   - descubre cuentas IMAP
   - usa `logins.json` + `key4.db` a traves de NSS
   - se conecta por IMAP con la configuracion real del perfil
   - lee mensajes recientes
   - puntua importancia por heuristica
   - puede enriquecer la cualificacion con el LLM
3. Expuse endpoints:
   - `GET /api/nexus/mail/status`
   - `GET /api/nexus/mail/priority`
4. Integre la superficie en `Nexus Operator` con una tarjeta nueva de correo prioritario.
5. Ajuste la seleccion de perfil para preferir `default-release` cuando existe.

## Que toque

- `app/config.py`
- `app/nexus/api/dependencies/auth.py`
- `app/nexus/api/routes/mail.py`
- `app/nexus/bootstrap.py`
- `app/nexus/mail/__init__.py`
- `app/nexus/mail/service.py`
- `app/templates/nexus_v1.html`
- `app/static/css/nexus_v1.css`
- `app/static/js/nexus_v1.js`
- `tests/e2e/test_nexus_v1_api.py`
- `tests/unit/test_thunderbird_mail_service.py`

## Tests

- `python -m pytest tests\unit\test_thunderbird_mail_service.py tests\e2e\test_nexus_v1_api.py tests\unit\test_config.py -q`
  - `33 passed`

- `python -m pytest tests\unit\test_outreach_service.py tests\unit\test_desktop_runtime.py -q`
  - `12 passed`

## Validacion local real

Sobre la instancia local:

- `GET /api/nexus/mail/status`
  - detecto correctamente:
    - `vicentearaizeta@sls.assetsconsultores.es`
    - `MayteRojas@sls.assetsconsultores.es`

- `GET /api/nexus/mail/priority?limit=8`
  - conecto correctamente a ambas cuentas
  - en esta lectura concreta devolvio `0` mensajes priorizados

## Observaciones

- La integracion ya no depende de reconfigurar credenciales a mano si Thunderbird ya las tiene guardadas.
- El paso siguiente natural es meter:
  - acciones sobre correo
  - seguimiento de replies
  - pipeline comercial ligado a inbox y outreach
