# Prospecting Local Architecture

## Objetivo

Evolucionar `Sales` para que la prospección funcione con:

- `Brave Search API` para discovery web
- `modelo local` vía endpoint OpenAI-compatible
- `CRM interno` como fuente de verdad
- ejecución larga/nocturna sin depender de tokens cloud

## Descubrimiento real del proyecto

### 1. Integración local LLM ya existente

Se ha encontrado soporte reutilizable para LLM local/OpenAI-compatible en:

- [C:\DEV\Nexus-UI\app\config.py](C:/DEV/Nexus-UI/app/config.py)
  - `llm_api_base_url`
  - `llm_l0_url`
  - `llm_l0_model`
  - comentarios explícitos de `LMStudio / Ollama`
- [C:\DEV\Nexus-UI\app\agents\llm_router.py](C:/DEV/Nexus-UI/app/agents/llm_router.py)
  - hace llamadas `POST /chat/completions`
  - sirve para OpenAI-compatible
- [C:\DEV\Nexus-UI\desktop\storage\provider_config.py](C:/DEV/Nexus-UI/desktop/storage/provider_config.py)
  - persistencia de proveedor remoto/local en desktop
- [C:\DEV\Nexus-UI\app\main.py](C:/DEV/Nexus-UI/app/main.py)
  - endpoints desktop de configuración de proveedor:
    - `GET /api/desktop/providers`
    - `PUT /api/desktop/providers`
- [C:\DEV\Nexus-UI\docs\REMOTE_ROUTER_CPU_SETUP.md](C:/DEV/Nexus-UI/docs/REMOTE_ROUTER_CPU_SETUP.md)
  - describe stack `LiteLLM + Ollama`

Conclusión:

No existía un cliente especializado para prospección, pero sí había base clara para reutilizar el patrón OpenAI-compatible y la configuración local.

### 2. Integración Brave existente

No se ha encontrado una implementación útil y viva de `Brave Search API` dentro del código operativo de Nexus.

Se han buscado cadenas como:

- `BRAVE_API_KEY`
- `BRAVE_SEARCH_API_KEY`
- `BRAVE_TOKEN`
- `search.brave.com`
- `api.search.brave`
- `BraveSearch`

Resultado:

- no había cliente backend reaprovechable de Brave en la parte útil del proyecto
- sí aparecía mucho ruido de `Brave browser` o bundles ajenos, pero no integración de API para prospección

Conclusión:

Había que crear `BraveSearchClient`.

### 3. Integración CRM existente

Sí existe integración reusable y ya era la buena:

- [C:\DEV\Nexus-UI\app\nexus\connectors\crm\assets.py](C:/DEV/Nexus-UI/app/nexus/connectors/crm/assets.py)
- [C:\DEV\Nexus-UI\app\nexus\crm\service.py](C:/DEV/Nexus-UI/app/nexus/crm/service.py)
- backend real en [C:\DEV\GitHub\assets-web-api\backend\api](C:/DEV/GitHub/assets-web-api/backend/api)

Campos y flujos comerciales relevantes confirmados:

- `Company`
- `pipeline_stage`
- `CRMNote`
- rutas `pipeline/*`

Conclusión:

La prospección debe escribir ahí. No debe crear otro CRM.

## Arquitectura final de este módulo

### Capa de brief

- [C:\DEV\Nexus-UI\app\nexus\prospecting\models.py](C:/DEV/Nexus-UI/app/nexus/prospecting/models.py)
- `ProspectingBrief`

Verticales soportadas:

- `public_administration`
- `restaurants`
- `custom`

### Capa de búsqueda

- [C:\DEV\Nexus-UI\app\nexus\prospecting\brave.py](C:/DEV/Nexus-UI/app/nexus/prospecting/brave.py)
- `BraveSearchClient`

Responsabilidades:

- ejecutar búsquedas
- respetar rate limit
- persistir bruto de cada query en `data/prospecting/raw`

### Capa de modelo local

- [C:\DEV\Nexus-UI\app\nexus\prospecting\llm.py](C:/DEV/Nexus-UI/app/nexus/prospecting/llm.py)
- `LocalLLMClient`

Responsabilidades:

- hablar con endpoint OpenAI-compatible local
- extraer JSON estructurado
- soportar `dry-run`

### Capa de extracción

- [C:\DEV\Nexus-UI\app\nexus\prospecting\extractors.py](C:/DEV/Nexus-UI/app/nexus/prospecting/extractors.py)
- `WebProspectExtractor`

Responsabilidades:

- descargar web principal
- seguir páginas relevantes
- extraer:
  - nombre
  - dominio
  - emails
  - teléfonos
  - dirección
  - señales de calidad
  - enlaces sociales

### Capa de validación

- [C:\DEV\Nexus-UI\app\nexus\prospecting\validators.py](C:/DEV/Nexus-UI/app/nexus/prospecting/validators.py)

Validadores:

- `EmailValidator`
- `DomainValidator`
- `MXValidator`

### Capa de scoring

- [C:\DEV\Nexus-UI\app\nexus\prospecting\scoring.py](C:/DEV/Nexus-UI/app/nexus/prospecting/scoring.py)
- `ProspectScorer`

Scoring por vertical:

- administración pública
- restaurantes

### Orquestador

- [C:\DEV\Nexus-UI\app\nexus\prospecting\service.py](C:/DEV/Nexus-UI/app/nexus/prospecting/service.py)
- `ProspectingAgentService`

Fases persistidas del run:

- `pending`
- `searching`
- `extracting`
- `validating`
- `scoring`
- `pushing_to_crm`
- `completed`
- `failed`

Funciones clave:

- generar queries
- usar Brave
- enriquecer con modelo local si está habilitado
- extraer señales web
- deduplicar contra CRM
- puntuar
- preparar o crear lead en CRM
- reanudar runs fallidos

### Persistencia

- [C:\DEV\Nexus-UI\app\nexus\prospecting\repository.py](C:/DEV/Nexus-UI/app/nexus/prospecting/repository.py)

Persistencia de:

- runs en `data/prospecting/prospecting_runs.json`
- bruto de búsqueda en `data/prospecting/raw/*.json`

## Integración frontend

Pantalla mínima:

- [C:\DEV\Nexus-UI\app\templates\nexus_sales.html](C:/DEV/Nexus-UI/app/templates/nexus_sales.html)
- [C:\DEV\Nexus-UI\app\static\js\nexus_sales.js](C:/DEV/Nexus-UI/app/static/js/nexus_sales.js)

La pantalla permite:

- elegir vertical
- geografía
- volumen
- score mínimo
- criterios de entrada
- lanzar run
- ver progreso
- ver resultados
- ver descartados
- empujar válidos al CRM
- reanudar run

## Decisiones importantes

### Nexus manda

`Nexus` decide. `n8n` queda para flows concretos cuando haga falta.

### CRM manda

`assets-web-api` es la fuente de verdad. La prospección solo enriquece y escribe ahí.

### Local first

El módulo está preparado para:

- `Ollama`
- `LM Studio`
- cualquier endpoint OpenAI-compatible local

### Brave no estaba resuelto

Por eso se ha añadido cliente nuevo y persistencia cruda.

## Huecos honestos

- No hay validación SMTP activa desde este módulo
- La reanudación hoy reejecuta el run, no hace checkpoint fino por candidato
- El modelo local se usa como ayuda de clasificación/expansión; no bloquea el flujo si no está disponible

## Siguiente mejora razonable

- checkpoints por candidato para runs largos
- colas persistentes reales para nocturnos
- probes SMTP controlados
- mejores fuentes para restauración/reviews de restaurantes
