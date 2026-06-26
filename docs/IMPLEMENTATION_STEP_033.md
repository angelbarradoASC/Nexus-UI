# IMPLEMENTATION STEP 033

## Paso
Persistencia local de proveedor remoto LLM para `Open-Nexus` y pantalla propia de configuración dentro del menú del desktop.

## Qué he hecho
- Añadida persistencia local del proveedor remoto del LLM en el escritorio, bajo `LOCALAPPDATA/Open-Nexus/config/llm_provider.json`.
- Añadido modelo de datos para guardar:
  - `provider_type`
  - `provider_label`
  - `api_base_url`
  - `api_key`
  - `model`
  - `enabled`
  - `updated_at`
- El runtime desktop ahora carga esa configuración al arrancar y la aplica encima de la configuración global para que `Open-Nexus` funcione con modelos remotos y no dependa de nada local.
- Añadidos endpoints desktop:
  - `GET /api/desktop/providers`
  - `PUT /api/desktop/providers`
- Al guardar desde la UI:
  - se persiste la configuración local
  - se reaplica al `cfg`
  - se resetea el `LLMRouter`
  - se reconstruye `app.state.nexus_runtime`
- Añadida una pantalla nueva:
  - `/open-nexus/models`
  - accesible desde el menú de `Open-Nexus`
- La pantalla permite editar:
  - etiqueta
  - tipo de proveedor
  - base URL
  - modelo
  - API key
  - activación del proveedor
- Se preserva la API key ya guardada si el usuario vuelve a guardar sin reescribirla.

## Qué he tocado
- `desktop/storage/provider_config.py`
- `desktop/storage/local_state.py`
- `desktop/config.py`
- `desktop/runtime/llm_provider_runtime.py`
- `desktop/opennexus/engine.py`
- `app/agents/llm_router.py`
- `app/main.py`
- `app/nexus/api/routes/ui.py`
- `app/templates/open_nexus.html`
- `app/templates/open_nexus_models.html`
- `app/static/js/open_nexus.js`
- `app/static/js/open_nexus_models.js`
- `app/static/css/open_nexus.css`
- `tests/unit/test_desktop_runtime.py`
- `tests/unit/test_open_nexus_engine.py`
- `tests/smoke/test_smoke_desktop.py`
- `tests/e2e/test_nexus_v1_api.py`

## Qué problema resuelve
Hasta ahora `Open-Nexus` tenía persistencia local de historial, pero no de proveedor LLM. Eso obligaba a depender del `.env` o de configuración externa para cambiar modelo, URL o API key.

Con este paso:
- el escritorio puede vivir apuntando a un servidor remoto de modelos
- la configuración queda guardada localmente
- el usuario la puede cambiar desde una pantalla propia del desktop
- el cambio se aplica al runtime sin tener que rehacer a mano el arranque

## Tests pasados
```powershell
python -m pytest tests\unit\test_desktop_runtime.py tests\unit\test_open_nexus_engine.py tests\smoke\test_smoke_desktop.py tests\e2e\test_nexus_v1_api.py -q
```

Resultado:
- `35 passed`

## Siguiente paso lógico
- Añadir prueba de conexión al proveedor remoto desde la propia pantalla de `Open-Nexus`
- Persistir perfiles múltiples de proveedor en vez de un único endpoint
- Sacar más workflows de negocio al shell desktop sin depender de superficies web auxiliares
