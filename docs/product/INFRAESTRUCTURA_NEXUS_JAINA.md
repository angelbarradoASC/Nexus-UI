# Infraestructura General - Nexus Desktop + JAINA

Estado documentado sobre la arquitectura real y la configuracion efectiva del producto a fecha de trabajo en este repositorio.

## 1. Reparto de responsabilidades

### Nexus Desktop

`Nexus` es el cliente local de escritorio.
Su trabajo es:

- ofrecer la interfaz operativa principal
- mantener estado local del usuario
- exponer un backend local FastAPI en `127.0.0.1`
- gobernar configuracion local de modelos e integraciones
- servir de puente entre la operativa local y los servicios remotos

### JAINA

`JAINA` es la capa remota de inteligencia y servicios de apoyo.
En la configuracion actual hace de:

- servidor de modelo local/remoto compatible con OpenAI
- punto de observabilidad centralizado
- posible ejecutor externo de automatizaciones
- cerebro compartido que debe poder ser consumido tanto por `desktop` como por `web`

## 2. Topologia operativa actual

### Arranque canonico del desktop

Durante desarrollo, el arranque canonico es:

- script: [start_open_nexus_desktop.ps1](C:\DEV\Nexus-UI\scripts\start_open_nexus_desktop.ps1)
- modo preferente: `pythonw -m desktop.main`

Ese script:

- copia `.env` al espacio local de datos del desktop
- mata procesos viejos del cliente si hace falta
- levanta el backend local
- espera a `/health`

### Backend local embebido

El backend local que sirve el desktop arranca desde:

- [local_server.py](C:\DEV\Nexus-UI\desktop\services\local_server.py)
- backend real: [app.py](C:\DEV\Nexus-UI\products\desktop\backend\app.py)

El `LocalServer` importa explicitamente `products.desktop.backend.app`, asi que esa es la app efectiva del desktop cuando se ejecuta desde fuente.

### Puerto y contexto local

- host local: `127.0.0.1`
- puerto local del desktop: `11430`
- health esperado: `http://127.0.0.1:11430/health`
- contexto esperado: `desktop_app`

### Datos locales del desktop

El estado local del producto vive en:

- raiz: `%LOCALAPPDATA%\Open-Nexus`
- resolucion desde codigo: [DesktopSettings](C:\DEV\Nexus-UI\desktop\config.py)

Subrutas relevantes:

- `config/`
- `logs/`
- `history/`

Ficheros importantes:

- proveedor LLM local: `%LOCALAPPDATA%\Open-Nexus\config\llm_provider.json`
- integraciones de observabilidad: `%LOCALAPPDATA%\Open-Nexus\config\monitoring_integrations.db`

## 3. Precedencia de configuracion

Hay dos niveles de configuracion que hoy conviven:

### Defaults de repositorio

El repositorio contiene valores base en `.env` y en `app/config.py`.
Sirven como base de arranque y fallback.

### Configuracion efectiva del desktop

La configuracion efectiva del producto `desktop` la mandan sus ficheros locales:

- `llm_provider.json`
- `monitoring_integrations.db`

Eso significa que la UI de `Configuracion` puede dejar el desktop funcionando con valores distintos a los del `.env`.

## 4. Estado efectivo confirmado del desktop

### Proveedor de IA activo

Segun el fichero local del desktop, el runtime LLM activo queda asi:

- tipo: `openai_compatible`
- etiqueta: `Servidor remoto`
- base URL: `http://192.168.1.150:11434/v1`
- modelo: `qwen2.5:3b`
- enabled: `true`

### Observabilidad efectiva

Segun la base local de integraciones del desktop, las fuentes activas del producto son:

- Prometheus: `http://192.168.1.150:9090`
- Grafana: `http://192.168.1.150:3000`
- Alertmanager: `http://192.168.1.150:9094`

Nota importante:

- el `.env` del repo sigue declarando `ALERTMANAGER_URL=http://192.168.1.150:9093`
- el desktop efectivo esta usando `9094` desde su base local

Si hay dudas visuales en `Operador`, primero mira la base local del desktop antes de tocar el `.env`.

## 5. JAINA como servidor compartido

La referencia remota actual del ecosistema es `192.168.1.150`.
Segun la configuracion y el codigo del repo, ahi viven o deben vivir:

- runtime LLM compatible con OpenAI
- Prometheus
- Grafana
- Alertmanager
- Loki como opcion preparada pero no necesariamente habilitada
- `n8n` como ejecutor externo de flujos

Sobre `n8n`:

- el repositorio lo trata como herramienta ejecutora, no como cerebro
- base codificada para automatizaciones: `http://192.168.1.150:5678`

## 6. Frontera entre desktop y servidor

### Lo que pertenece al desktop

- UI
- estado local de sesion
- configuracion local de proveedor e integraciones
- acceso rapido del operador
- historico local y logs del cliente
- desbloqueo y uso local del Vault

### Lo que pertenece a JAINA

- razonamiento remoto
- endpoint LLM principal
- observabilidad centralizada
- automatizaciones externas
- servicios reutilizables por `desktop` y por `web`

## 7. Superficies del producto desktop

Las pestanas activas hoy son:

- `Shell`
- `Operador`
- `Sales`
- `Configuracion`
- `Vault`
- `Campana`

Rutas UI:

- `/open-nexus`
- `/nexus-v1`
- `/nexus-sales`
- `/nexus/settings`
- `/nexus/vault`
- `/nexus/campaign`

El registro de estas rutas vive en:

- [ui.py](C:\DEV\Nexus-UI\products\desktop\routes\ui.py)

## 8. Backends y routers reutilizados

El desktop no es un mock.
Monta routers reales FastAPI desde:

- chat
- monitoring
- incidents
- audit
- crm
- outreach
- prospecting
- prompts
- cmdb
- vault
- campaign
- agents

El bootstrap de producto esta en:

- [bootstrap.py](C:\DEV\Nexus-UI\products\desktop\bootstrap.py)

## 9. Regla de diseno para siguientes cambios

- `Nexus` siempre se documenta y se prueba como `desktop`
- la configuracion viva del desktop manda sobre defaults del repo
- `JAINA` debe verse como infraestructura servidora comun
- todo lo que sea logica reutilizable debe acabar sirviendo tanto a `desktop` como a `web`
- `Sales` no se debe mezclar con configuracion operativa salvo por dependencias compartidas de infraestructura

## 10. Puntos de entrada para un chat nuevo

Si el siguiente chat va de `Sales`, lo minimo que hay que saber sin reexplorar todo el arbol es:

- el desktop se arranca con [start_open_nexus_desktop.ps1](C:\DEV\Nexus-UI\scripts\start_open_nexus_desktop.ps1)
- el backend efectivo del desktop es [app.py](C:\DEV\Nexus-UI\products\desktop\backend\app.py)
- la pestana `Sales` es [nexus_sales.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\nexus_sales.html)
- su logica de cliente esta en [nexus_sales.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\nexus_sales.js)
- el modelo remoto actual del desktop apunta a `192.168.1.150:11434/v1`
- `n8n` se considera ejecutor externo, no capa de decision
