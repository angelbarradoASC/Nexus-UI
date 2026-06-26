# IMPLEMENTATION STEP 020

## Paso
Hacer un deep dive de tecnologias habituales en empresa para diversificar el enfoque de `Nexus` antes de seguir conectando adaptadores concretos.

## Que hago
- Defino los dominios operativos principales que suelen existir en una empresa:
  - puesto de usuario
  - identidad
  - Linux
  - Windows
  - virtualizacion
  - contenedores
  - red
  - firewalls
  - storage
  - bases de datos
  - middleware
  - aplicaciones
  - cloud
  - SaaS
  - observabilidad
- Para cada dominio documento:
  - tecnologias tipicas
  - tipos de activo
  - señales habituales
  - metodos de acceso
  - capacidades de observacion
  - capacidades de accion
  - prioridad para Nexus
- Cierro una taxonomia objetivo inicial para que el sistema no nazca sesgado a una sola tecnologia.

## Que toco
- `docs/DEEP_DIVE_TECNOLOGIAS_EMPRESA.md`

## Resultado
`Nexus` ya tiene una referencia de arquitectura para diversificar el producto como asistente general de operaciones y no como suma de integraciones aisladas.

## Tests
- No aplica

## Observaciones
- Este paso no mete conectores nuevos.
- Lo que hace es fijar el mapa correcto para decidir que familias se implementan primero y como se agrupan.
