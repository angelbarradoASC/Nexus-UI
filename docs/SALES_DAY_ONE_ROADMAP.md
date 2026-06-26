# Sales Day One Roadmap

## Objetivo

Mañana Nexus debe permitir lanzar el primer bloque de prospección y dejar trazabilidad comercial en el CRM interno de Assets.

## Sistema fuente

La fuente de verdad comercial no es Odoo.

La base correcta está en:

- [assets-web-api backend](C:/DEV/GitHub/assets-web-api/backend)
- [assets-web-api private area](C:/DEV/GitHub/assets-web-api/frontend/PRIV)

Modelos y endpoints clave:

- `Company` en [models.py](C:/DEV/GitHub/assets-web-api/backend/api/models.py)
- `CRMNote` en [models.py](C:/DEV/GitHub/assets-web-api/backend/api/models.py)
- `pipeline/*` en [pipeline_views.py](C:/DEV/GitHub/assets-web-api/backend/api/pipeline_views.py)
- `admin/companies/*` en [company_views.py](C:/DEV/GitHub/assets-web-api/backend/api/company_views.py)

## Resultado mínimo para mañana

1. Cargar un CSV de 3 prospectos en Nexus.
2. Lanzar campaña en `dry-run`.
3. Preparar sincronización al CRM interno.
4. Tener en el CRM:
   - empresa/prospecto
   - contacto
   - fuente `cold`
   - etapa `new`
   - siguiente seguimiento
   - nota inicial generada por Nexus

## Orden operativo

### 1. Verificar acceso al CRM interno

- Configurar en `.env`:
  - `ASSETS_CRM_BASE_URL`
  - `ASSETS_CRM_USERNAME`
  - `ASSETS_CRM_PASSWORD`
- Validar `GET /api/nexus/crm/status`

### 2. Preparar los 3 primeros prospectos

Campos mínimos:

- `email`
- `first_name`
- `company`
- `company_domain`

Opcionales recomendados:

- `job_title`
- `notes`

### 3. Lanzar outreach en simulación

- Crear campaña desde `/nexus-v1`
- Mantener `dry-run`
- Revisar asunto y cuerpo

### 4. Preparar sincronización CRM

- Usar el botón `Preparar 3 leads`
- Revisar preview de sincronización
- Confirmar que cada prospecto tiene:
  - `Company`
  - `pipeline_stage = new`
  - `lead_source = cold`
  - `CRMNote` inicial

### 5. Activar envío real

- Añadir credenciales SMTP/IMAP manualmente
- Quitar `dry-run`
- Enviar solo a 3 contactos

### 6. Registrar actividad posterior

Tras cada envío real, Nexus debe terminar haciendo:

- actualizar `last_contact`
- mantener `next_followup`
- registrar `CRMNote` de email
- mover a `contacted`

## Riesgos controlados

- No duplicar empresas por dominio.
- No enviar más de 3 correos en el primer bloque.
- No escribir en CRM sin credenciales explícitas.
- No depender de integración local de modelos.

## Siguiente paso técnico

Después del bloque de mañana:

1. sincronización automática post-envío
2. lectura de respuestas por Thunderbird
3. cambio automático de etapa en pipeline
4. creación de tareas internas cuando la respuesta requiera acción humana
