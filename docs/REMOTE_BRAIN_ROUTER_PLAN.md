# REMOTE BRAIN AND MESSAGE ROUTER PLAN

## Estado verificado

Servidor remoto accesible por SSH:

- host: `192.168.1.150`
- hostname: `llmpro`
- usuario verificado: `angel`
- sistema: `Ubuntu 24.04.4 LTS`
- CPU: `Intel i5-11320H`, `8 vCPU`
- RAM: `15 GiB`
- disco libre: `82 GiB`
- GPU: `no-gpu`

Servicios verificados:

- `n8n` activo en `http://192.168.1.150:5678`
- `n8n` corriendo como `systemd service`
- `Node.js v20.20.2`
- `npm 10.8.2`
- `Python 3.12.3`

Conclusión importante:

Este servidor no debe alojar inferencia local de modelos.
Debe alojar:

- el cerebro de orquestación remota
- el enrutador de mensajes
- adaptadores a APIs de modelos externos
- y, cuando toque, conectores como `n8n`

## Principio de diseño

`Nexus` sigue siendo el cerebro principal.

Eso significa:

- el escritorio `Open-Nexus` es el puesto de mando
- el servidor remoto es el runtime remoto de agentes
- `n8n` es una herramienta ejecutora, no un segundo cerebro
- los LLM viven fuera, detrás de APIs

## Qué vamos a construir

### 1. Servidor de cerebro remoto

Un servicio ligero, mantenido en el servidor Ubuntu, con estas funciones:

- recibir peticiones de `Nexus`
- aplicar políticas de enrutado de mensajes
- hablar con uno o varios proveedores LLM externos
- centralizar claves, modelos y endpoints
- exponer una API sencilla para desktop/web

No debe:

- renderizar UI
- tomar el control del producto
- duplicar CRM, correo o lógica de escritorio

### 2. Enrutador de mensajes

El enrutador debe decidir, para cada petición:

- qué tipo de mensaje es
- qué agente o skill toca
- qué proveedor LLM usar
- qué nivel de coste/latencia admite
- si requiere llamar a un flow de `n8n`

La salida del router debe ser uniforme:

- `kind`
- `intent`
- `target_surface`
- `llm_profile`
- `tool_calls`
- `n8n_flow` si aplica

### 3. Registro de proveedores LLM remotos

Como el servidor no va a inferir modelos, debe actuar como concentrador de proveedores:

- OpenAI-compatible
- Anthropic-compatible si hace falta un adaptador
- Gemini
- Groq
- OpenRouter
- endpoint propio de Claude si lo dejáis expuesto detrás de API

La primera versión debe priorizar un único contrato interno:

- `chat completion`
- `streaming` opcional
- `model alias`
- `provider profile`

## Arquitectura recomendada

### Capa 1. Desktop

`Open-Nexus`

- UI
- sesión local
- persistencia local
- prompt del usuario
- revisión humana

### Capa 2. Remote Brain

Servicio en `llmpro`

- router de mensajes
- perfiles LLM
- control de claves
- observabilidad
- adaptadores de tool calling

### Capa 3. Executors

- `n8n`
- correo
- CRM
- HTTP tools
- otros conectores

## Decisión tecnológica recomendada

Para este servidor, recomiendo esto:

### Cerebro remoto

Python + FastAPI

Motivo:

- ya encaja con Nexus
- más fácil de mantener con lo que ya tenemos
- mejor para tipado y contratos internos
- más natural para compartir dominio con el proyecto actual

### Router de mensajes

Implementación propia ligera dentro del mismo servicio FastAPI.

No montaría aún otra pieza extra tipo gateway separado salvo que el tráfico crezca.

### Adaptador de proveedores

Contrato interno común tipo:

- `POST /v1/router/chat`
- `POST /v1/router/classify`
- `POST /v1/router/dispatch`

Y por debajo, adaptadores para:

- OpenAI-compatible
- Gemini
- Groq
- OpenRouter

### `n8n`

Se integra por webhook o por API, pero siempre invocado desde `Nexus` o desde el cerebro remoto.

`n8n` no clasifica.
`n8n` no decide.
`n8n` ejecuta.

## Orden de implementación

### Fase 0. Base verificada

Ya hecha:

- SSH verificado
- capacidad del host verificada
- `n8n` verificado

### Fase 1. Cerebro remoto mínimo

Construir un servicio FastAPI remoto con:

- `health`
- `provider registry`
- `message router`
- `single chat endpoint`

Objetivo:

que `Open-Nexus` pueda apuntar a una sola URL remota y olvidarse de proveedores individuales.

### Fase 2. Router de mensajes

Añadir clasificación mínima:

- `general`
- `sales`
- `mail`
- `incident`
- `ops`

Y un perfil de modelo por clase de mensaje.

### Fase 3. Ejecución externa

Añadir llamadas controladas a:

- `n8n`
- endpoints internos
- CRM
- correo

### Fase 4. Observabilidad

Registrar:

- latencia
- proveedor usado
- modelo usado
- coste estimado
- tool calls
- errores por flow

## Perfiles de modelo sugeridos

### `fast-general`

Para chat y clasificación rápida.

### `mail-draft`

Para outreach y respuesta de correo.

### `ops-diagnostic`

Para diagnosis técnica con más contexto.

### `reasoning-heavy`

Para casos complejos o decisiones delicadas.

## Cómo va ahora mismo

Va bien en lo importante:

- el servidor existe
- entra por SSH
- está limpio
- `n8n` está arriba
- y el host encaja mejor como cerebro remoto que como servidor de inferencia

Eso nos evita un error bastante caro:

intentar meter modelos locales donde no toca.

## Siguiente paso recomendado

El siguiente paso correcto no es tocar `n8n`.

Es montar el servicio remoto mínimo del cerebro en `llmpro` con:

- FastAPI
- registry de proveedores
- router de mensajes
- endpoint de chat único para `Open-Nexus`

Y luego hacer que el desktop apunte a ese servicio como backend remoto de inteligencia.
