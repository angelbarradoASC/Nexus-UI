# Pestana Sales

## Objetivo

`Sales` es la superficie de prospeccion y flujo comercial dentro de Nexus.
Es una pieza que ya funciona razonablemente bien y debe evolucionar sin romperse ni rehacerse por capricho.

## Ruta y archivos

- ruta UI: `/nexus-sales`
- template: [nexus_sales.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\nexus_sales.html)
- cliente JS: [nexus_sales.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\nexus_sales.js)
- estilos: reutiliza `nexus_v1.css`

## Estructura actual

La pantalla se reparte en dos columnas:

### Columna izquierda

- entrada libre de briefing
- boton `Interpretar con IA`
- resumen de busqueda
- chips `must have`
- chips `nice to have`
- tags CRM
- barra de lanzamiento de prospeccion
- parametros avanzados
- bloque de exclusiones

### Columna derecha

- salida de interpretacion IA
- panel de agentes autonomos
- KPIs del run
- acciones de CRM
- mensaje de estado
- logs del run
- tabla de resultados

## Endpoints principales

El frontend de `Sales` usa, entre otros:

- `/api/nexus/prospecting/interpret`
- `/api/nexus/prospecting/run`
- `/api/nexus/prospecting/runs/{id}`
- `/api/nexus/prospecting/runs/{id}/resume`
- `/api/nexus/prospecting/runs/{id}/logs`
- `/api/nexus/prospecting/discarded`
- `/api/nexus/prospecting/push-valid-to-crm`
- `/api/nexus/prospecting/results/{id}/push-to-crm`
- `/api/nexus/prospecting/api-budget`
- `/api/nexus/crm/status`
- `/api/nexus/outreach/status`
- `/api/nexus/outreach/events`
- `/api/nexus/outreach/launch`
- `/api/nexus/automations`

## Dependencias de IA y descubrimiento

La prospeccion actual se apoya en:

- LLM compatible con OpenAI
- proveedor local/remoto principal configurado desde desktop
- Brave Search
- Google Places
- CRM interno

## Flujo agentico actual

`Sales` ya no funciona como un parser con unas pocas heuristicas.
Ahora expone una tuberia autonoma minima de 7 agentes:

1. `brief_guardian`
2. `brief_refiner`
3. `source_strategist`
4. `query_architect`
5. `search_executor`
6. `candidate_qualifier`
7. `crm_packager`

Flujo real:

1. el usuario escribe un briefing libre
2. `brief_guardian` revisa huecos, ambiguedades y guardrails
3. `/api/nexus/prospecting/interpret` lo convierte a brief estructurado
4. `brief_refiner` mejora criterios sin tocar intencion ni geografia
5. `source_strategist` decide el `source_plan`
6. `query_architect` arma queries y expansiones de bajo ruido
7. `search_executor` intenta primero la fuente principal
8. si no llena cupo suficiente, cae al origen secundario
9. `candidate_qualifier` hace extraccion, validacion, dedupe y scoring
10. `crm_packager` deja el handoff listo para CRM

La UI de `Sales` ya pinta la traza de estos agentes en un panel propio.

## Guardrails actuales

En la fase de refinado, el sistema debe preservar:

- `vertical`
- `city`
- `province`
- `region`
- `represented_by`
- `desired_count`
- `minimum_score`
- `dry_run`

Solo puede refinar:

- `target_description`
- `must_have`
- `nice_to_have`
- `exclude`
- `crm_tags`
- `preferred_sources`

## Plan de fuentes

La prospeccion ya soporta decision de origen y fallback real.

Fuentes actuales:

- `google_places`
- `brave`

Comportamiento esperado:

- `Places` es la unica fuente de discovery
- `Brave` no descubre leads: solo enriquece candidatos ya encontrados en `Places`
- si no hay geografia usable o `Places` no aplica, el run debe quedarse sin discovery antes que inventar leads via `Brave`

## Prompts vivos que gobiernan Sales

La capa de IA agentica de `Sales` ya no se gobierna solo desde codigo.
Estos prompts viven en `Configuracion > Prompting`, grupo `sales`:

- `sales.prospecting.interpret`
- `sales.prospecting.guardrails`
- `sales.prospecting.refine`
- `sales.prospecting.source_strategy`
- `sales.prospecting.query_planner`
- `sales.prospecting.search_audit`
- `sales.prospecting.classify_candidate`
- `sales.prospecting.crm_packager`

Regla importante:

- si cambia el texto de uno de estos prompts, cambia el comportamiento real del flujo de prospeccion
- no hace falta tocar codigo para ajustar interpretacion, guardrails, estrategia de fuentes, planificacion de queries, auditoria de discovery, clasificacion o handoff CRM

## Reglas de producto

- `Sales` no se mezcla con configuracion operativa salvo lo estrictamente compartido
- `Sales` debe mantener fallback de IA y resiliencia de proveedor
- `n8n` no debe convertirse en el cerebro comercial
- la decision comercial debe seguir perteneciendo a la capa Nexus/JAINA

## Relacion con JAINA

`Sales` consume el cerebro remoto, pero su UX y su estado local siguen viviendo en el desktop.
La idea de fondo es que la logica de negocio acabe siendo reutilizable desde `web` sin rehacer el dominio.
