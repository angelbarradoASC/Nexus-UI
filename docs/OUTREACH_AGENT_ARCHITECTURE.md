# Outreach Agent for Nexus

## Objetivo

Montar un agente de outreach B2B de bajo volumen dentro de Nexus para:

- recibir prospectos en CSV o JSON
- redactar correos con un LLM cloud
- ejecutar una secuencia simple:
  - contacto inicial
  - follow-up 1
  - follow-up 2
- enviar por SMTP
- consultar salud basica del buzón por IMAP
- dejar trazabilidad simple de campañas y envios

## Modelo recomendado

Para este caso de uso, la mejor opcion inicial es `Gemini 3.5 Flash`.

Motivos:

- calidad alta para redaccion en espanol profesional
- latencia normalmente baja
- tier gratuito oficial desde Google AI Studio
- API compatible con OpenAI, asi que encaja con el `LLMRouter` de Nexus sin rehacer el stack

Alternativa:

- `Groq` si priorizamos latencia por encima de calidad de redaccion

## Como obtener la API key gratis

### Gemini

1. Entrar en Google AI Studio
2. Crear o usar el proyecto free que se genera por defecto
3. Ir a `API keys`
4. Crear la key
5. Configurar Nexus con:

```env
LLM_PRIORITY=cost
LLM_L1_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_L1_KEY=tu_api_key
LLM_L1_MODEL=gemini-3.5-flash
```

### Groq

1. Crear cuenta en Groq Console
2. Generar `API key`
3. Configurar Nexus con:

```env
LLM_PRIORITY=cost
LLM_L1_URL=https://api.groq.com/openai/v1
LLM_L1_KEY=tu_api_key
LLM_L1_MODEL=openai/gpt-oss-20b
```

## Modulos

### `app/nexus/outreach/prompts.py`

Prompt de sistema para redaccion de outreach B2B en espanol.

### `app/nexus/outreach/repository.py`

Persistencia simple en fichero:

- `campaigns.json`
- `events.jsonl`

### `app/nexus/outreach/transports.py`

Conectores:

- `SMTPOutreachTransport`
- `IMAPMailboxMonitor`

### `app/nexus/outreach/service.py`

Servicio principal:

- parseo de prospectos
- creacion de campaña
- ejecucion de correos pendientes
- generacion con LLM
- envio o simulacion
- logging de eventos

### `app/nexus/api/routes/outreach.py`

Endpoints:

- `GET /api/nexus/outreach/status`
- `GET /api/nexus/outreach/campaigns`
- `GET /api/nexus/outreach/events`
- `POST /api/nexus/outreach/launch`
- `POST /api/nexus/outreach/campaigns/{campaign_id}/run-due`

## Flujo

1. El operador carga una campaña desde la UI o la API.
2. Nexus valida y normaliza prospectos.
3. El agente construye el prompt por prospecto y paso de secuencia.
4. El LLM devuelve `subject` y `body`.
5. Nexus:
   - si `dry_run=true`, solo deja preview
   - si `dry_run=false`, envia por SMTP
6. El evento queda logado.
7. El prospecto pasa a `waiting_followup` o `completed`.

## Riesgo operativo

Se deja orientado a volumen bajo:

- cap diario configurable
- secuencia corta
- primer uso recomendado en `dry-run`
- trazabilidad local simple

## CSV minimo

Ver ejemplo en:

- [outreach_prospects_example.csv](C:/DEV/Nexus-UI/examples/outreach_prospects_example.csv)
