# IMPLEMENTATION STEP 043

## Objetivo

Aislar el producto desktop del producto web y cortar la dependencia mas toxica:
el cliente Python no debe arrancar sobre `app/main.py`.

## Cambios

- nuevo backend desktop:
  - `products/desktop/backend/app.py`
- nuevo bootstrap desktop:
  - `products/desktop/bootstrap.py`
- nuevas rutas UI desktop:
  - `products/desktop/routes/ui.py`
- nueva arborescencia de producto:
  - `products/desktop`
  - `products/web`
- templates y static del desktop copiados a:
  - `products/desktop/ui/templates`
  - `products/desktop/ui/static`
- templates y static de web copiados a:
  - `products/web/ui/templates`
  - `products/web/ui/static`
- `LocalServer` del cliente Python ahora importa:
  - `products.desktop.backend.app`

## Validacion

### Tests

```powershell
python -m pytest tests\unit\test_desktop_backend_app.py tests\smoke\test_smoke_desktop.py tests\unit\test_desktop_application.py tests\unit\test_open_nexus_entrypoint.py -q
```

Resultado:
- `17 passed`

### Runtime real

Se relanzo `python -m desktop.main` y se valido:

- `GET http://127.0.0.1:11430/health`
  - `redis: false`
  - `mongodb: false`
  - `backend: desktop`
- `GET /open-nexus`
  - devuelve la marca `open-nexus desktop product`
- `GET /nexus-sales`
  - devuelve la marca `open-nexus desktop product sales`

## Nota honesta

El desktop ya esta aislado en backend y superficie visual.
Todavia comparte parte del motor con el stack historico web.
El siguiente corte tiene que bajar a runtime, rutas API y config.

