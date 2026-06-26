# Orquestación de agentes

Este documento define cómo se coordinan los agentes de Nexus sin caer en caos acoplado.

## Principios

- un agente no decide política global
- un agente no ejecuta fuera de su ámbito
- el coordinador central decide el siguiente paso
- toda acción con efecto lateral debe pasar por policy y audit

## Tipos de agente

### 1. Agentes conversacionales

- reciben peticiones de usuario
- analizan intención
- piden contexto adicional
- preparan acciones o respuestas

### 2. Agentes de monitorización

- observan métricas y alertas
- enriquecen señales con contexto
- disparan diagnósticos o escalados

### 3. Agentes de incidente

- convierten alertas o eventos en incidentes operables
- aplican runbooks
- abren o actualizan ticketing

### 4. Agentes de ejecución

- lanzan acciones en herramientas o runtimes
- informan resultado, no deciden estrategia

## Orquestador central

La pieza central es `NexusCoordinator`.

Responsabilidades:

- aceptar una entrada
- resolver el tipo de flujo
- invocar JAINA cuando toque
- encadenar agentes y conectores
- registrar auditoría
- cerrar el flujo con estado final

## Flujos principales

### Flujo de chat

`input usuario -> coordinator -> JAINA/router -> skill/agent -> execution/response -> audit`

### Flujo de alerta

`alertmanager/api -> monitoring pipeline -> incident pipeline -> diagnosis -> action or ticket -> audit`

### Flujo de tarea local

`desktop/runtime event -> coordinator -> policy -> connector or MCP -> result -> audit`

## Decisiones de control

Antes de ejecutar una acción con efecto:

1. validar identidad y origen
2. validar policy y riesgo
3. comprobar conectores requeridos
4. crear contexto de auditoría
5. ejecutar
6. guardar resultado y estado

## Estados comunes

- `received`
- `classified`
- `enriched`
- `ready_to_execute`
- `executing`
- `resolved`
- `escalated`
- `failed`
- `cancelled`

