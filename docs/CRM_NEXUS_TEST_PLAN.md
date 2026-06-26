# CRM + Nexus Test Plan

## Objetivo

Dejar preparadas las pruebas que tenemos que ejecutar para no perdernos cuando enlacemos CRM, correo, outreach y agentes.

Este documento está pensado como checklist de validación real.

## Alcance actual

Queremos validar:

- consistencia de ficha de cliente
- consistencia de actividad y seguimiento
- integridad de las notas CRM
- sincronización correcta entre Nexus y CRM
- comportamiento esperado al leer correo y reflejarlo en CRM

## Entornos implicados

### CRM interno

- `assetsconsultores.es/PRIV/clientes.html`
- backend `assets-web-api`

### Nexus

- `C:/DEV/Nexus-UI`

### Correo

- Thunderbird / IMAP

### Automatización

- `n8n` solo si un flujo concreto participa

## Bloque A. Pruebas de ficha CRM

### A1. Guardado visible

Pasos:

1. abrir cliente
2. editar un campo simple
3. comprobar que se activan botones de guardado
4. guardar
5. reabrir ficha

Esperado:

- cambio persistido
- estado de “sin cambios” restaurado

### A2. Descartar cambios

Pasos:

1. abrir cliente
2. cambiar varios campos
3. pulsar descartar

Esperado:

- la ficha vuelve al estado inicial
- no se persiste nada

### A3. Cierre con cambios pendientes

Pasos:

1. abrir cliente
2. tocar un campo
3. cerrar ficha

Esperado:

- confirmación de salida
- no perder cambios por accidente

## Bloque B. Pruebas de seguimiento

### B1. Nueva nota con seguimiento futuro

Pasos:

1. abrir cliente con seguimiento vencido
2. crear nota nueva
3. asignar `next_followup` futuro
4. guardar actividad

Esperado:

- el cliente deja de figurar como vencido
- la próxima acción muestra la nueva fecha
- el histórico muestra la nueva actividad

### B2. Marcar actividad como hecha

Pasos:

1. localizar actividad pendiente
2. marcarla hecha

Esperado:

- la actividad cambia de estado
- si era la actividad que mandaba sobre el seguimiento, el sistema recalcula la próxima acción

### B3. Editar actividad pendiente

Pasos:

1. editar nota existente
2. cambiar `next_followup`
3. guardar

Esperado:

- el nuevo seguimiento manda
- no queda el aviso de vencido si ya no toca

### B4. Borrar actividad pendiente

Pasos:

1. borrar actividad con seguimiento

Esperado:

- la próxima acción se recalcula
- no queda enganchada una fecha vieja

## Bloque C. Pruebas de layout del modal

### C1. Modal a zoom 100%

Pasos:

1. abrir cliente en zoom normal
2. abrir modal de edición

Esperado:

- se llega al pie sin bajar zoom
- `Guardar cambios` es accesible con scroll normal

### C2. Modal con histórico largo

Pasos:

1. abrir cliente con muchas actividades
2. abrir modal

Esperado:

- el histórico hace scroll
- el pie sigue accesible
- la pantalla no obliga a reducir zoom

## Bloque D. Pruebas Nexus -> CRM

### D1. Crear prospecto desde Nexus

Pasos:

1. cargar prospecto en Nexus
2. sincronizarlo al CRM

Esperado:

- se crea `Company`
- se crea nota inicial si aplica
- se ve en la lista del CRM

### D2. Guardar outreach en CRM

Pasos:

1. lanzar campaña en `dry-run`
2. luego en real

Esperado:

- el envío deja nota
- cambia `last_contact`
- cambia `pipeline_stage` si aplica
- fija `next_followup`

### D3. Respuesta comercial entrante

Pasos:

1. simular correo de respuesta
2. hacer pasar a Nexus por clasificación

Esperado:

- se detecta el cliente correcto
- se crea nota CRM
- se propone o aplica cambio de etapa

## Bloque E. Pruebas de matching

### E1. Matching por email

Esperado:

- si el dominio o contacto ya existe, no se crea empresa duplicada

### E2. Matching por nombre

Esperado:

- si coincide nombre y no hay dominio fiable, se pide revisión o se marca con cautela

## Bloque F. Pruebas de agentes futuras

### F1. Sales Inbox Agent

Esperado:

- clasifica correo
- propone acción
- no escribe basura en CRM

### F2. Outreach Agent

Esperado:

- redacta con tono útil
- registra envío
- no dispara volumen excesivo

### F3. Pipeline Agent

Esperado:

- mueve etapa con criterio
- deja trazabilidad de cada cambio

## Payloads de ejemplo

Usar estos archivos:

- `C:/DEV/Nexus-UI/examples/crm_nexus/sample_company_sync.json`
- `C:/DEV/Nexus-UI/examples/crm_nexus/sample_inbound_email.json`
- `C:/DEV/Nexus-UI/examples/crm_nexus/sample_outreach_campaign.json`

## Criterio de salida

No damos por “cerrada” una integración CRM + Nexus hasta que pasen:

- pruebas de ficha
- pruebas de seguimiento
- pruebas de layout
- pruebas de escritura CRM desde Nexus

Y, muy importante:

no volver a marcar como arreglado algo que no se haya probado en navegador real cuando el problema sea de UX o flujo visual.
