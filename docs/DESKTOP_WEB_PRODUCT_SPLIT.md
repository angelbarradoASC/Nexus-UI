# Desktop / Web Product Split

## Decision

Desde esta iteracion tratamos **desktop** y **web** como dos productos distintos.

- `products/desktop` es la superficie prioritaria de `Open-Nexus`
- `products/web` queda como superficie web separada

## Estado actual

### Desktop

- backend propio: `products/desktop/backend/app.py`
- bootstrap propio: `products/desktop/bootstrap.py`
- rutas UI propias: `products/desktop/routes/ui.py`
- templates propios: `products/desktop/ui/templates`
- static propios: `products/desktop/ui/static`

El cliente Python ya arranca contra este backend propio.

### Web

- arbol de producto creado: `products/web`
- templates copiados: `products/web/ui/templates`
- static copiados: `products/web/ui/static`

## Lo que ya no hace el desktop

- no importa `app/main.py`
- no intenta conectar a Redis al arrancar
- no intenta conectar a Mongo al arrancar
- no sirve los templates desde `app/templates`

## Lo que todavia comparte motor

Todavia se reutilizan capas de dominio y algunas rutas API desde el stack historico:

- `nexus.api.routes.*`
- `nexus.api.dependencies.auth`
- servicios de CRM, mail, outreach, prospecting y coordinator
- `agents.llm_router`
- `config`, `metrics`, `exceptions`, `utils`

## Siguiente corte recomendado

1. duplicar las rutas API de desktop dentro de `products/desktop`
2. duplicar el runtime builder del desktop
3. mover config, metrics y utils del desktop a su propio namespace
4. dejar la web libre para evolucionar sin arrastrar al cliente Python

