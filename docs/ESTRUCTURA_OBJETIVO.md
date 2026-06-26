# Estructura objetivo

La ruta nueva de construcción vive en `app/nexus/`.

No sustituye todavía al código actual. Es la estructura destino para migrar con seguridad.

## Árbol principal

```text
app/nexus/
  api/
  application/
  audit/
  connectors/
  core/
  domain/
  execution/
  incidents/
  memory/
  monitoring/
  observability/
  orchestration/
  policy/
  shared/
  workers/
```

## Criterios

- `api`: HTTP y contratos
- `application`: casos de uso y servicios
- `domain`: entidades y reglas de negocio
- `connectors`: dependencias externas
- `orchestration`: coordinación entre agentes
- `monitoring` e `incidents`: verticales críticas de negocio
- `execution`, `policy`, `audit`, `memory`: capacidades transversales

## Estrategia de migración

1. mantener `app/main.py` y `worker/worker.py` operativos
2. implementar módulos nuevos en `app/nexus/`
3. mover rutas y flujos uno a uno
4. retirar la estructura antigua solo cuando el tráfico real ya pase por la nueva

