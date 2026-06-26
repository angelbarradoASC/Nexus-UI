# Implementation Step 042

## Objetivo

Responder al nuevo prompt de prospección local-first:

- Brave Search API
- modelo local OpenAI-compatible
- CRM reutilizado
- verticales públicas + restaurantes + custom
- runs persistidos y reanudables

## Trabajo realizado

### Descubrimiento documentado

- [C:\DEV\Nexus-UI\docs\prospecting_local_architecture.md](C:/DEV/Nexus-UI/docs/prospecting_local_architecture.md)

### Nueva arquitectura de prospección

- [C:\DEV\Nexus-UI\app\nexus\prospecting\models.py](C:/DEV/Nexus-UI/app/nexus/prospecting/models.py)
- [C:\DEV\Nexus-UI\app\nexus\prospecting\llm.py](C:/DEV/Nexus-UI/app/nexus/prospecting/llm.py)
- [C:\DEV\Nexus-UI\app\nexus\prospecting\brave.py](C:/DEV/Nexus-UI/app/nexus/prospecting/brave.py)
- [C:\DEV\Nexus-UI\app\nexus\prospecting\extractors.py](C:/DEV/Nexus-UI/app/nexus/prospecting/extractors.py)
- [C:\DEV\Nexus-UI\app\nexus\prospecting\validators.py](C:/DEV/Nexus-UI/app/nexus/prospecting/validators.py)
- [C:\DEV\Nexus-UI\app\nexus\prospecting\scoring.py](C:/DEV/Nexus-UI/app/nexus/prospecting/scoring.py)
- [C:\DEV\Nexus-UI\app\nexus\prospecting\service.py](C:/DEV/Nexus-UI/app/nexus/prospecting/service.py)

### Persistencia mejorada

- [C:\DEV\Nexus-UI\app\nexus\prospecting\repository.py](C:/DEV/Nexus-UI/app/nexus/prospecting/repository.py)
  - `prospecting_runs.json`
  - `raw/*.json`

### API nueva

- [C:\DEV\Nexus-UI\app\nexus\api\schemas\prospecting.py](C:/DEV/Nexus-UI/app/nexus/api/schemas/prospecting.py)
- [C:\DEV\Nexus-UI\app\nexus\api\routes\prospecting.py](C:/DEV/Nexus-UI/app/nexus/api/routes/prospecting.py)

Rutas nuevas:

- `POST /api/nexus/prospecting/run`
- `POST /api/nexus/prospecting/runs/{run_id}/resume`
- `GET /api/nexus/prospecting/runs/{run_id}`
- `GET /api/nexus/prospecting/results`
- `GET /api/nexus/prospecting/discarded`
- `POST /api/nexus/prospecting/results/{result_id}/push-to-crm`
- `POST /api/nexus/prospecting/push-valid-to-crm`

### UI de Sales rehecha

- [C:\DEV\Nexus-UI\app\templates\nexus_sales.html](C:/DEV/Nexus-UI/app/templates/nexus_sales.html)
- [C:\DEV\Nexus-UI\app\static\js\nexus_sales.js](C:/DEV/Nexus-UI/app/static/js/nexus_sales.js)

### Ejemplos

- [C:\DEV\Nexus-UI\examples\prospecting\brief_public_administration_madrid_toledo.json](C:/DEV/Nexus-UI/examples/prospecting/brief_public_administration_madrid_toledo.json)
- [C:\DEV\Nexus-UI\examples\prospecting\brief_restaurants_madrid.json](C:/DEV/Nexus-UI/examples/prospecting/brief_restaurants_madrid.json)
- [C:\DEV\Nexus-UI\examples\prospecting\brief_restaurants_zaragoza.json](C:/DEV/Nexus-UI/examples/prospecting/brief_restaurants_zaragoza.json)
- [C:\DEV\Nexus-UI\examples\prospecting\brief_restaurants_salamanca.json](C:/DEV/Nexus-UI/examples/prospecting/brief_restaurants_salamanca.json)

### README

- [C:\DEV\Nexus-UI\docs\PROSPECTING_AGENT_README.md](C:/DEV/Nexus-UI/docs/PROSPECTING_AGENT_README.md)

## Tests añadidos

- [C:\DEV\Nexus-UI\tests\unit\test_prospecting_agent_service.py](C:/DEV/Nexus-UI/tests/unit/test_prospecting_agent_service.py)

Se cubre:

- generación de queries por vertical
- validación de email
- scoring restaurante
- scoring administración pública
- push preview a CRM
- run completo mockeado
- resume run
- extracción JSON de `LocalLLMClient`
- persistencia raw de `BraveSearchClient`

## Estado honesto

### Sí queda hecho

- el módulo ya no está acoplado a “municipal”
- existe cliente local LLM
- existe cliente Brave
- existe run persistido con fases
- existe reanudación básica
- existe UI mínima en Sales

### No queda cerrado aún

- no hay SMTP probe real
- la reanudación reejecuta el run completo
- la calidad final depende de qué endpoint local y qué modelo conectes
- sin `BRAVE_SEARCH_API_KEY` ni endpoint local no hay prueba end-to-end real contra servicios externos
