# ProspectingAgent README

## Qué hace

`ProspectingAgent` es el módulo de prospección local-first de `Nexus Sales`.

Sirve para lanzar briefs como:

- `Prospecta 20 ayuntamientos cercanos a Torrejón de la Calzada`
- `Prospecta 30 restaurantes de categoría en Zaragoza`

y ejecutar el flujo:

1. genera queries
2. busca con Brave
3. analiza webs
4. valida dominios y MX
5. puntúa por vertical
6. deduplica contra CRM
7. prepara push al CRM

## Variables de entorno

### Modelo local

- `LOCAL_LLM_ENABLED`
- `LOCAL_LLM_BASE_URL`
- `LOCAL_LLM_MODEL`
- `LOCAL_LLM_PROVIDER`
- `LOCAL_LLM_API_KEY`
- `LOCAL_LLM_TIMEOUT`
- `LOCAL_LLM_RETRIES`

Si no se ponen, el módulo intenta reutilizar `LLM_L0_URL` y `LLM_L0_MODEL`.

### Brave

- `BRAVE_SEARCH_API_KEY`
- `BRAVE_SEARCH_ENABLED`
- `BRAVE_SEARCH_RATE_LIMIT`

## Endpoints

- `POST /api/nexus/prospecting/run`
- `POST /api/nexus/prospecting/runs/{run_id}/resume`
- `GET /api/nexus/prospecting/runs/{run_id}`
- `GET /api/nexus/prospecting/results`
- `GET /api/nexus/prospecting/discarded`
- `POST /api/nexus/prospecting/results/{result_id}/push-to-crm`
- `POST /api/nexus/prospecting/push-valid-to-crm`

## Ejemplos de briefs

Ver:

- [C:\DEV\Nexus-UI\examples\prospecting\brief_public_administration_madrid_toledo.json](C:/DEV/Nexus-UI/examples/prospecting/brief_public_administration_madrid_toledo.json)
- [C:\DEV\Nexus-UI\examples\prospecting\brief_restaurants_madrid.json](C:/DEV/Nexus-UI/examples/prospecting/brief_restaurants_madrid.json)
- [C:\DEV\Nexus-UI\examples\prospecting\brief_restaurants_zaragoza.json](C:/DEV/Nexus-UI/examples/prospecting/brief_restaurants_zaragoza.json)
- [C:\DEV\Nexus-UI\examples\prospecting\brief_restaurants_salamanca.json](C:/DEV/Nexus-UI/examples/prospecting/brief_restaurants_salamanca.json)

## Persistencia

- runs: `data/prospecting/prospecting_runs.json`
- bruto Brave: `data/prospecting/raw/*.json`

## Modo largo/nocturno

Si activas `async_mode`:

- el run se lanza
- se guarda estado
- puedes ir recargando la ficha del run
- si falla, puedes reanudarlo

## Qué no hace aún

- enviar emails
- hacer SMTP probe real
- checkpoint granular por candidato

Eso vendrá después. Ahora mismo el foco es discovery + validación + CRM.
