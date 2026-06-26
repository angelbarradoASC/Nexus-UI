# Nexus Agent Architecture

## Principio base

Los agentes de Nexus viven en servidor y exponen el mismo contrato para:

- `desktop`
- `web`

El cliente no contiene logica agentica de negocio. Solo consume:

- catalogo de agentes
- runs
- planes
- pasos
- skill calls
- resultados y explicaciones

## Estructura canonica

```text
app/nexus/agents/
  shared/
    base.py
    context.py
    registry.py
    result.py
  supervisor/
    agent.py
    manifest.py
  operator/
    agent.py
    manifest.py
    skills_map.py
  shell/
    agent.py
    manifest.py
    execution_policy.py
  sales/
    agent.py
    manifest.py
```

## Roles iniciales

### `supervisor`

- clasifica intencion
- decide el siguiente agente
- explica el plan y el por que

### `operator`

- observabilidad
- alarmas
- incidentes
- runbooks

### `shell`

- ejecucion remota
- recogida de evidencia
- acciones aprobadas

### `sales`

- prospeccion
- CRM
- outreach

## Contratos comunes

El backend comparte estos modelos:

- `AgentRequest`
- `AgentManifest`
- `PlanStep`
- `SkillCall`
- `AgentRun`

Se exponen por API en:

- `GET /api/nexus/agents/catalog`
- `POST /api/nexus/agents/runs`
- `GET /api/nexus/agents/runs`
- `GET /api/nexus/agents/runs/{run_id}`

## Modelo de entrega actual

- los cerebros agenticos viven en servidor
- desktop y web consumen el mismo catalogo y los mismos runs
- el chat clasico sigue intacto mientras evolucionamos la capa agentica sin romper lo que ya funciona

## Regla de ubicacion

Si una pieza debe ser consumida por desktop y web, va en servidor.

Solo se permite logica especifica de cliente en:

- plantillas
- CSS
- JS
- integraciones locales del desktop
