# Pestana Campana

## Objetivo

`Campana` gobierna la prospeccion automatica programada.
No sustituye a `Sales`: la complementa para ejecuciones recurrentes y controladas.

## Ruta y archivos

- ruta UI: `/nexus/campaign`
- template: [nexus_campaign.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\nexus_campaign.html)
- cliente JS: [nexus_campaign.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\nexus_campaign.js)
- estilos: [nexus_campaign.css](C:\DEV\Nexus-UI\products\desktop\ui\static\css\nexus_campaign.css)

## Estructura actual

### Panel izquierdo

- estado del scheduler
- proxima ejecucion
- ultima ejecucion
- reporte del ultimo run
- boton `Ejecutar ahora`

### Panel derecho

- configuracion de la campana
- toggle de habilitado
- parametros de vertical, objetivo, geografia, volumen y CTA

## Endpoints usados

Base:

- `/api/nexus/campaign`

Rutas consumidas desde cliente:

- `/api/nexus/campaign/status`
- `/api/nexus/campaign/trigger`
- `/api/nexus/campaign/config`

## Backend relacionado

El backend desktop inicializa un scheduler y le adjunta el agente de campana dentro de:

- [app.py](C:\DEV\Nexus-UI\products\desktop\backend\app.py)

## Papel dentro del producto

`Campana` es la pieza que permite pasar de prospeccion manual a prospeccion operada.
Su funcion es orquestar cadencias, no redisenar la logica de seleccion de leads.
