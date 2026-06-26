# Roadmap de producción

Este roadmap prioriza poner Nexus en producción de forma estable antes de perseguir sofisticación adicional.

## Fase 0

Base operativa y de control.

- cerrar arquitectura canónica
- consolidar `app/nexus/` como ruta objetivo
- definir contratos de API de chat, monitorización e incidentes
- definir política de riesgo y auditoría mínima

## Fase 1

Nexus v1 usable.

- migrar chat y orquestación básica al coordinador nuevo
- conectar Alertmanager y Prometheus desde conectores dedicados
- crear pipeline de alertas e incidentes
- separar worker general, worker de monitorización y worker de incidentes
- unificar auditoría de acciones y estado de tareas

## Fase 2

Integraciones productivas.

- cerrar integración Jira
- cerrar integración ServiceNow
- cerrar integración MCP
- establecer desktop bridge para ejecución local y telemetría
- introducir memoria operativa útil, no experimental

## Fase 3

Hardening de producción.

- timeouts, retries y circuit breakers por conector
- colas diferenciadas por prioridad
- métricas y tracing de todos los flujos críticos
- idempotencia en ingestión de alertas e incidentes
- tests e2e de alarmas, ticketing y ejecución controlada

## Fase 4

Crecimiento controlado.

- runbooks más ricos
- automatización con aprobación por política
- correlación previa al incidente
- handoff mejor entre Nexus, JAINA y Hive Mind

## Criterios de salida a producción

No deberíamos dar una versión por “lista” si no cumple esto:

- cada acción crítica deja auditoría
- cada integración tiene manejo explícito de error
- cada incidente tiene estado y trazabilidad
- las alertas son idempotentes y no se duplican sin control
- existe separación entre leer, diagnosticar y ejecutar
- hay forma de desactivar automatismos de riesgo

