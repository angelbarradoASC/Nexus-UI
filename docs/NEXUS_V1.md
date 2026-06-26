# Nexus v1

`Nexus v1` es la primera versión realista y productizable del sistema.

No intenta resolver todo el ecosistema. Su objetivo es operar bien, ser auditable y escalar sin rehacerse entero.

## Misión

Nexus es el plano de control y ejecución de la plataforma:

- recibe entradas de usuario, API y webhooks
- clasifica y orquesta tareas
- consulta a JAINA cuando necesita razonamiento
- ejecuta herramientas, conectores y MCPs con control
- gestiona alertas, incidencias y respuestas operativas
- deja trazabilidad de cada acción

## Límites de v1

Nexus v1 no persigue:

- autonomía irrestricta
- correlación avanzada tipo Hive Mind
- decenas de integraciones a la vez
- automatizaciones de alto riesgo sin guardrails

## Capacidades de v1

### Conversación

- chat web y desktop
- contexto de conversación
- selección de agente o modo
- streaming de respuesta

### Ejecución

- catálogo de skills y herramientas
- ejecución local y remota controlada
- política de permisos y riesgo
- auditoría de acciones

### Monitorización

- lectura de alertas desde Alertmanager
- consultas de contexto a Prometheus
- ingestión de métricas y alertas de agentes locales
- respuesta operativa básica: clasificar, silenciar, escalar, diagnosticar

### Incidentes

- entrada por API/webhook
- normalización del evento
- generación de incidente interno
- diagnóstico automatizable
- reparación cuando haya runbook o flujo permitido
- creación o actualización de ticket externo

### Integraciones

- Jira
- ServiceNow
- SSH y accesos remotos
- MCPs internos
- runtime local desktop

## Módulos de v1

- `api`: entrada HTTP, webhooks y contratos
- `orchestration`: coordinación de agentes, skills y flujos
- `monitoring`: alertas, métricas y respuesta operativa
- `incidents`: ciclo de vida del incidente
- `execution`: ejecución de acciones y herramientas
- `connectors`: puentes a Jira, ServiceNow, Prometheus, Alertmanager y MCP
- `policy`: permisos, límites y decisiones de riesgo
- `audit`: registro estructurado de acciones
- `memory`: memoria operativa y aprendizaje utilizable
- `workers`: procesos asíncronos y pipelines largos

## Arquitectura de despliegue

La forma objetivo de producción para v1 es:

1. `web api`
2. `worker general`
3. `worker monitoring`
4. `worker incidents`
5. `redis`
6. `mongodb`
7. `prometheus / alertmanager / grafana`

## Regla de operación

JAINA decide mejor.
Nexus ejecuta mejor.
Hive Mind correlacionará mejor, pero no bloquea v1.

