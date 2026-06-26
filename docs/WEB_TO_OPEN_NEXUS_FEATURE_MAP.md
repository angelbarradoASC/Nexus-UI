# Web To Open-Nexus Feature Map

## Objetivo

Este documento lista lo que hoy existe en la superficie web de Nexus y cómo debe aterrizar en `Open-Nexus`, que es el producto de escritorio ejecutable.

La idea no es copiar la web 1:1.
La idea es conservar la funcionalidad útil y reubicarla en una experiencia de trabajo de escritorio.

## Funcionalidades que hoy existen en la web

### 1. Chat general

Hoy existe:

- timeline de conversación
- envío de mensajes
- selección de modo (`general`, `monitoring`, `incident`)
- prompts rápidos

Valor real:

- entrada unificada para pedir contexto, diagnóstico o acción

En Open-Nexus:

- pasa a ser el shell principal
- no debe vivir como caja de chat visual, sino como consola de órdenes y respuestas
- el modo no debe ir en un selector siempre visible; debe inferirse por routing y mostrarse como resultado

### 2. Estado de recolección

Hoy existe:

- lista de recolectores
- estado global
- refresco automático

Valor real:

- saber si Prometheus, Alertmanager y futuras fuentes están arriba

En Open-Nexus:

- pasa a panel lateral o comando `/runtime`
- no hace falta una tarjeta grande
- debe mostrarse como estado operativo compacto

### 3. Correo prioritario Thunderbird

Hoy existe:

- detección de cuentas
- lectura de mensajes
- cualificación básica
- vista de mensajes importantes

Valor real:

- bandeja de trabajo comercial y operativa

En Open-Nexus:

- debe convertirse en un inbox operacional local
- acceso por comando y panel
- prioridad visible
- acciones futuras: responder, convertir en lead, delegar, archivar

### 4. Outreach comercial

Hoy existe:

- carga de CSV
- definición de campaña
- propuesta/CTA/audiencia
- dry-run
- eventos de campaña

Valor real:

- lanzar prospección y revisar borradores

En Open-Nexus:

- debe pasar a workflow guiado
- no como formulario largo fijo
- idealmente:
  - crear campaña
  - cargar prospectos
  - revisar borradores
  - lanzar

### 5. CRM interno

Hoy existe:

- estado del conector
- sincronización de leads al CRM interno
- visibilidad de campañas/pending

Valor real:

- enlazar Nexus con la verdad comercial de Assets

En Open-Nexus:

- debe quedar integrado en el flujo de campaña y correo
- no como tarjeta separada de métricas
- el usuario debería notar “se ha registrado en CRM”, no “voy a otra caja y pulso otro botón”

### 6. Actividad / historial / outreach feed

Hoy existe:

- pestañas de actividad
- historial
- feed de outreach

Valor real:

- trazabilidad operativa

En Open-Nexus:

- debe ser journal local del asistente
- una vista de timeline sí tiene sentido
- pero más compacta y orientada a sesión de trabajo

### 7. Editor de prompts

Hoy existe:

- catálogo de prompts
- edición
- reset
- persistencia

Valor real:

- afinar el cerebro de Nexus sin tocar código

En Open-Nexus:

- debe quedarse
- probablemente como herramienta avanzada o panel de configuración
- no tiene por qué ser la vista principal del producto

## Qué no debe migrar tal cual

- layout de dashboard web con tres columnas fijas
- tarjetas grandes de estado
- sensación de “panel de control corporativo”
- dependencia conceptual de URLs y navegación entre páginas

## Qué sí debe mantenerse

- capacidades reales
- routing por skills
- trazabilidad
- integración correo
- integración CRM
- prompt tuning
- diagnóstico operativo

## Traducción de producto

La web actual contiene estas familias funcionales:

- conversación
- observabilidad
- correo
- ventas
- CRM
- configuración de prompts

En Open-Nexus eso debe reordenarse como:

1. Shell principal
2. Panel lateral de estado
3. Bandeja de trabajo
4. Workflows guiados
5. Configuración avanzada

## Decisión de UX

Open-Nexus no debe ser:

- “la web antigua en un webview”

Open-Nexus debe ser:

- shell-first
- workflow-first
- local-first
- con paneles auxiliares cuando aporten valor
