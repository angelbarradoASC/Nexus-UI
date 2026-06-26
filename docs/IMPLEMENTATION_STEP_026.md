# Implementation Step 026

## Paso
Panel vivo para editar todos los prompts de Nexus desde la propia aplicacion.

## Que he hecho
- He creado un catalogo central de prompts editables para Nexus.
- He cableado los prompts reales de agentes, outreach, cualificacion de correo y prediagnosticos para que lean del gestor comun.
- He añadido persistencia de overrides en `data/prompts/overrides.json`.
- He creado API para listar, leer, editar y resetear prompts.
- He creado la pagina `/nexus-prompts` para editar los prompts manualmente.
- He enlazado esa pagina desde `/nexus-v1`.
- He reforzado el prompt base de outreach para reducir el tono artificial y las frases tipicas de IA comercial.

## Que he tocado
- `C:\DEV\Nexus-UI\app\nexus\prompts\catalogue.py`
- `C:\DEV\Nexus-UI\app\nexus\prompts\service.py`
- `C:\DEV\Nexus-UI\app\nexus\prompts\__init__.py`
- `C:\DEV\Nexus-UI\app\config.py`
- `C:\DEV\Nexus-UI\app\nexus\api\dependencies\auth.py`
- `C:\DEV\Nexus-UI\app\nexus\orchestration\coordinator.py`
- `C:\DEV\Nexus-UI\app\nexus\bootstrap.py`
- `C:\DEV\Nexus-UI\app\nexus\api\routes\ui.py`
- `C:\DEV\Nexus-UI\app\nexus\api\routes\prompts.py`
- `C:\DEV\Nexus-UI\app\nexus\api\schemas\prompts.py`
- `C:\DEV\Nexus-UI\app\templates\nexus_v1.html`
- `C:\DEV\Nexus-UI\app\templates\nexus_prompts.html`
- `C:\DEV\Nexus-UI\app\static\css\nexus_v1.css`
- `C:\DEV\Nexus-UI\app\static\css\nexus_prompts.css`
- `C:\DEV\Nexus-UI\app\static\js\nexus_prompts.js`
- `C:\DEV\Nexus-UI\app\agents\generation_agent.py`
- `C:\DEV\Nexus-UI\app\agents\intention_agent.py`
- `C:\DEV\Nexus-UI\app\agents\analyst_agent.py`
- `C:\DEV\Nexus-UI\app\agents\coder_agent.py`
- `C:\DEV\Nexus-UI\app\agents\researcher_agent.py`
- `C:\DEV\Nexus-UI\app\nexus\outreach\service.py`
- `C:\DEV\Nexus-UI\app\nexus\mail\service.py`

## Que tests he pasado
- `python -m pytest tests\unit\test_prompt_manager.py tests\e2e\test_nexus_prompts_api.py -q`
  - `4 passed`
- `python -m pytest tests\unit\test_llm_router.py tests\unit\test_outreach_service.py tests\e2e\test_nexus_v1_api.py -q`
  - `22 passed`

## Validacion manual
- `GET /api/nexus/prompts` devuelve el catalogo completo.
- `GET /api/nexus/prompts/outreach.system` devuelve el prompt reforzado de outreach.
- `GET /nexus-prompts` devuelve `200`.
- La app web de Nexus se ha reiniciado para cargar el sistema nuevo.
