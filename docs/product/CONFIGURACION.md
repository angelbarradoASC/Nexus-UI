# Pestana Configuracion

## Objetivo

`Configuracion` es la superficie de gobierno del desktop.
No es una pantalla cosmetica: desde aqui se decide como arranca Nexus, a que servidor de IA apunta y que fuentes de observabilidad usa `Operador`.

## Ruta y archivos

- ruta UI: `/nexus/settings`
- template: [nexus_settings.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\nexus_settings.html)
- cliente JS: [nexus_settings.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\nexus_settings.js)
- estilos: [nexus_settings.css](C:\DEV\Nexus-UI\products\desktop\ui\static\css\nexus_settings.css)

## Secciones internas

Aunque en la navbar parece una sola pestana, internamente tiene cuatro paneles:

- `General`
- `Prompting`
- `Modelos`
- `Operator`

## General

Muestra:

- contexto del runtime
- URL de arranque
- rutas locales del producto
- conteo de integraciones de observabilidad

Endpoint:

- `/api/desktop/settings/summary`

## Prompting

Permite editar prompts vivos del sistema.

Endpoints:

- `/api/nexus/prompts`
- `/api/nexus/prompts/{key}`
- `/api/nexus/prompts/{key}/reset`

### Grupo `sales`

Desde aqui ya se gobierna tambien la nueva capa agentica de `Sales`.

Prompts activos actuales:

- `sales.prospecting.interpret`
- `sales.prospecting.guardrails`
- `sales.prospecting.refine`
- `sales.prospecting.source_strategy`
- `sales.prospecting.query_planner`
- `sales.prospecting.search_audit`
- `sales.prospecting.classify_candidate`
- `sales.prospecting.crm_packager`

Cada uno controla una fase distinta:

- interpretar briefing libre
- auditar guardrails del prompt original
- refinar con guardrails
- decidir sesgo de fuentes
- expandir queries
- auditar discovery bruto
- clasificar candidatos
- empaquetar readiness para CRM

Reglas importantes:

- editar estos prompts cambia el comportamiento real de `Sales`
- no hay que tocar codigo para afinar el flujo comercial base
- los cambios de texto sobre prompts ya existentes aplican sobre runtime vivo
- si se anaden nuevas claves de prompt al catalogo, el desktop debe reiniciarse para que aparezcan en la UI porque el backend embebido no va con autoreload

## Modelos

Gobierna el proveedor LLM del desktop.

Endpoints:

- `/api/desktop/providers`

Persistencia local:

- `%LOCALAPPDATA%\Open-Nexus\config\llm_provider.json`

Regla importante:

- el proveedor guardado aqui manda sobre el `.env` del repo para el desktop

## Operator

Gobierna las integraciones de observabilidad consumidas por `Operador`.

Endpoints:

- `/api/desktop/operator/integrations`
- `/api/desktop/operator/integrations/test`
- `/api/desktop/operator/integrations/{integration_id}`

Persistencia local:

- `%LOCALAPPDATA%\Open-Nexus\config\monitoring_integrations.db`

Reglas importantes:

- desde aqui se crean, editan y eliminan fuentes
- esta base local manda sobre defaults del repositorio
- hoy solo se exponen `prometheus`, `grafana` y `alertmanager`

## Papel en la arquitectura

Esta pestana es la bisagra entre:

- el cliente local Nexus
- el servidor remoto JAINA
- la observabilidad centralizada

Si el desktop se comporta raro, casi siempre hay que mirar primero esta pantalla.
