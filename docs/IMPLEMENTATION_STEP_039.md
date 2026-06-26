# Implementation Step 039

## Objetivo

Seguir la implantación del circuito `correo -> Nexus -> CRM`, cerrando un primer flujo real para que un correo entrante pueda convertirse en actividad comercial dentro del CRM interno.

## Qué he implementado

He añadido un endpoint nuevo en Nexus:

- `POST /api/nexus/crm/mail/ingest`

Archivos tocados:

- `C:/DEV/Nexus-UI/app/nexus/api/routes/crm.py`
- `C:/DEV/Nexus-UI/app/nexus/api/schemas/crm.py`
- `C:/DEV/Nexus-UI/app/nexus/crm/service.py`

## Qué hace el flujo nuevo

Recibe un payload de correo entrante y:

- valida remitente
- ignora dominios internos de Assets
- busca empresa por dominio en el CRM
- construye payload de empresa, pipeline y nota
- en `dry-run` devuelve preview
- en modo real actualiza pipeline y registra la nota CRM

## Regla actual

Esta primera versión usa:

- matching por dominio
- clasificación sugerida por `classification_hint`
- mapeo básico de etapa comercial

Mapa actual de hints:

- `positive_reply` -> `meeting`
- `meeting_request` -> `meeting`
- `proposal_request` -> `proposal`
- `pricing_request` -> `proposal`
- `customer_request` -> `contacted`
- `neutral_reply` -> `contacted`
- `negative_reply` -> `lost`

## Qué no hace todavía

- matching avanzado por contacto o nombre de empresa
- lectura automática directa desde la bandeja al endpoint
- creación de tareas o reuniones derivadas
- clasificación LLM dentro del propio bridge CRM

## Pruebas pasadas

Archivo:

- `C:/DEV/Nexus-UI/tests/unit/test_crm_bridge_service.py`

Resultado:

- `5 passed`

Casos cubiertos:

- sync de campaña en preview
- sync de campaña real
- ingestión de correo en preview
- ingestión de correo real reutilizando empresa existente
- ignorado correcto de dominios internos

## Siguiente bloque natural

Conectar este endpoint con:

- correo prioritario de Thunderbird
- bandeja de Nexus
- y más adelante el orquestador comercial

para que un correo relevante pueda acabar en CRM con un solo gesto o de forma asistida.
