# CRM + Nexus Integration Blueprint

## Objetivo

Dejar fijada la arquitectura buena entre `Nexus`, el correo, `n8n` y el CRM interno de Assets para que no volvamos a duplicar lógica ni a repartir criterio entre varios sistemas.

La regla canónica es esta:

- El CRM es la fuente de verdad comercial.
- Nexus es la capa operativa e inteligente.
- `n8n` es una herramienta de automatización bajo demanda, no otro cerebro.

## Sistemas implicados

### CRM interno

Repositorio:

- `C:/DEV/GitHub/assets-web-api`

Piezas relevantes:

- `backend/api/models.py`
- `backend/api/pipeline_views.py`
- `backend/api/company_views.py`
- `frontend/PRIV/clientes.html`

Responsabilidad:

- guardar clientes/prospectos
- guardar notas y actividad comercial
- guardar `pipeline_stage`
- guardar `last_contact`
- guardar `next_followup`
- servir de auditoría comercial real

### Nexus

Repositorio:

- `C:/DEV/Nexus-UI`

Responsabilidad:

- recibir inputs del usuario o de agentes
- leer correo y clasificarlo
- redactar outreach o respuestas
- decidir la siguiente acción comercial
- actualizar CRM mediante API
- mantener contexto, prompts y trazabilidad operativa

### n8n

Responsabilidad:

- ejecutar flujos concretos cuando Nexus lo pida
- ayudar con IMAP/SMTP, parsing o pasos automáticos
- no almacenar criterio comercial como fuente principal

## Principio de diseño

No vamos a construir un CRM nuevo dentro de Nexus.

No vamos a dejar que `n8n` tome decisiones comerciales por su cuenta.

No vamos a repartir la verdad entre:

- Thunderbird
- Nexus
- n8n
- CRM

La única verdad comercial persistente debe acabar en el CRM.

## Flujo objetivo

### 1. Prospecto nuevo

Entrada posible:

- CSV
- correo entrante
- acción manual del usuario
- respuesta a campaña

Nexus hace:

- normaliza datos
- intenta hacer matching con `Company`
- si no existe, crea prospecto
- fija estado inicial
- registra primera actividad

Escrituras en CRM:

- `Company`
- `pipeline_stage = new` o `contacted`
- `CRMNote`
- `next_followup` si aplica

### 2. Outreach saliente

Nexus hace:

- redacta email
- decide CTA
- envía o deja preparado
- registra el envío en CRM

Escrituras en CRM:

- `last_contact`
- `pipeline_stage = contacted`
- `CRMNote` de tipo email
- `next_followup`

### 3. Respuesta entrante

Nexus hace:

- ingesta correo
- limpia el hilo
- clasifica intención
- decide si hay interés, bloqueo, rechazo o petición de propuesta

Escrituras en CRM:

- `CRMNote`
- cambio de `pipeline_stage` si procede
- actualización de `next_followup`

### 4. Seguimiento manual

El usuario hace:

- abre cliente
- registra llamada, nota o reunión
- cambia seguimiento

Nexus debe:

- refrescar contexto
- mantener consistencia visual
- no dejar datos viejos mandando sobre el siguiente seguimiento

## Contratos entre Nexus y CRM

### Lectura mínima

Nexus necesita leer:

- lista de empresas
- detalle de empresa
- notas por empresa
- estado de pipeline

### Escritura mínima

Nexus necesita poder:

- crear empresa/prospecto
- actualizar ficha CRM
- crear nota
- editar nota
- borrar nota
- mover etapa

## Modelo de agentes recomendado

### Sales Inbox Agent

Lee correos entrantes, limpia contexto y clasifica.

### Outreach Agent

Redacta secuencias y registra envíos.

### Pipeline Agent

Decide cambios de etapa y actualiza seguimiento.

### CRM Sync Agent

Se asegura de que toda acción relevante termine persistida en el CRM.

### Sales Orchestrator

Coordina los anteriores y decide cuándo entra cada uno.

## Regla de persistencia

Toda acción comercial relevante debe terminar en el CRM.

Ejemplos:

- correo enviado -> nota CRM
- llamada hecha -> nota CRM
- respuesta recibida -> nota CRM
- cambio de prioridad -> `next_followup`
- avance comercial -> `pipeline_stage`

## Integración con Open-Nexus

La versión desktop debe consumir esta misma lógica, pero no la misma UI.

La UI desktop puede tener:

- bandeja comercial
- cliente activo
- correo relacionado
- acción sugerida
- historial resumido

Pero las escrituras seguirán yendo al CRM interno.

## Riesgos a vigilar

- que `n8n` empiece a guardar lógica comercial por su cuenta
- que el correo y el CRM diverjan
- que una nota vieja siga mandando sobre un seguimiento nuevo
- que se dupliquen clientes por matching flojo
- que Nexus proponga acciones sin dejar rastro en CRM

## Decisión actual

La integración correcta es:

- CRM como fuente de verdad
- Nexus como capa operativa
- n8n como herramienta ejecutora

No vamos a construir un segundo CRM encubierto dentro de Nexus.
