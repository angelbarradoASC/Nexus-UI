# Pestana Shell

## Objetivo

`Shell` es la superficie operativa generalista del desktop.
Hoy funciona como base de trabajo ligera: chat local, rail de monitorizacion y una zona central todavia libre para crecer.

## Ruta y archivos

- ruta UI: `/open-nexus`
- template: [open_nexus.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\open_nexus.html)
- cliente JS: [open_nexus.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\open_nexus.js)
- estilos base: `open_nexus.css`

## Estructura actual

La pantalla esta dividida en tres piezas:

- una zona libre superior marcada como placeholder
- un mini chat IA
- un rail lateral de monitorizacion

## Integraciones que consume

Desde frontend llama a:

- `/api/nexus/monitoring/collectors`
- `/api/nexus/incidents`
- `/api/nexus/chat`

## Que hace hoy

- muestra el estado de recolectores
- muestra las ultimas alarmas/incidentes visibles en el lateral
- permite enviar mensajes cortos al chat local

## Que no debemos asumir

- no es una terminal real de sistema
- no es la superficie agentica densa
- la zona libre superior sigue siendo expansion pendiente

## Papel dentro del producto

`Shell` es la superficie mas flexible para operativa transversal y comandos dirigidos.
Si en el futuro hay una consola util dentro de Nexus, deberia nacer aqui.
