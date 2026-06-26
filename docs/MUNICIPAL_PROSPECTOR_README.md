# MunicipalProspector

`MunicipalProspector` es el flujo principal nuevo de la pantalla `Sales` dentro de Nexus.

## Objetivo

Pasar de un flujo centrado en CSV a un flujo de prospección activa:

1. buscar organismos públicos por zona
2. localizar web oficial
3. extraer contactos y evidencias
4. validar dominio y MX
5. puntuar el resultado
6. deduplicar contra el CRM interno
7. preparar o empujar el resultado al CRM

## Endpoints

- `POST /api/nexus/prospecting/municipal/run`
- `GET /api/nexus/prospecting/municipal/runs/{run_id}`
- `GET /api/nexus/prospecting/municipal/results`
- `GET /api/nexus/prospecting/municipal/discarded`
- `POST /api/nexus/prospecting/municipal/results/{result_id}/push-to-crm`
- `POST /api/nexus/prospecting/municipal/push-valid-to-crm`

## Implementacion actual

La primera version funcional usa:

- `Nominatim` para geocodificar la zona de busqueda
- `Overpass API` para descubrir ayuntamientos/organismos con presencia publica
- `BeautifulSoup` para analizar la home y paginas relevantes
- `dnspython` para validar DNS/MX
- el conector existente `AssetsCRMConnector` para deduplicar y escribir en el CRM

## Persistencia

Los runs se guardan en:

- `data/prospecting/municipal_runs.json`

Cada run guarda:

- request
- estado
- resultados
- descartados
- resumen

## Score actual

- `+25` web oficial verificada
- `+20` MX valido
- `+20` email confirmado visible
- `+15` responsable con cargo tecnologico
- `+10` telefono
- `+10` fuente tipo contacto/corporacion
- `-20` si solo hay correo generico no confirmado
- `-30` si el dominio no parece oficial
- `-50` si no hay canal usable

Clasificacion:

- `80-100`: `Alta`
- `50-79`: `Media`
- `20-49`: `Baja`
- `<20`: descartado

## Pantalla Sales

La pantalla `Sales` queda organizada asi:

- panel principal: `MunicipalProspector`
- rail lateral:
  - estado CRM
  - outreach secundario
  - actividad

El bloque de outreach se mantiene como apoyo, no como flujo principal.

## Limitaciones actuales

- la discovery depende de OSM/Overpass y puede no cubrir todos los organismos
- no hay validacion SMTP activa
- no se respeta todavia `robots.txt` de forma explicita
- el `push to CRM` esta pensado para arrancar en `dry-run`
- la clasificacion de cargos es heuristica, no LLM

## Siguiente capa recomendable

1. verificacion mas fina de webs oficiales
2. parser mejor de paginas de corporacion municipal
3. respeto explicito de `robots.txt`
4. revalidacion manual por resultado
5. push real al CRM desde la UI
