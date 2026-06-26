# Arquitectura Desktop

## Objetivo

La aplicacion de escritorio de `Nexus` no debe ser una copia de la web metida en una ventana.

Debe ser el runtime local del asistente general:

- arranca el backend local
- expone accesos al equipo
- corre agentes locales de bajo nivel
- ofrece atajos operativos
- sirve de puente entre skills, herramientas locales y la interfaz

## Referencia tomada

Se ha tomado como referencia conceptual `OpenCode`:

- asistente general
- permisos por capacidad
- varios modos de agente
- desktop y terminal como superficies del mismo motor

Lo que nos interesa de esa idea no es copiar su UI.

Lo que nos interesa es:

- separar core de superficie
- separar permisos de ejecucion
- separar agente principal de agentes auxiliares
- tratar desktop como runtime local y no como “visor”

## Estado actual del desktop

Antes de esta limpieza:

- `desktop/main.py` mezclaba arranque, servidor, monitor, tray y ventana
- el agente local de monitorizacion no tenia en cuenta el token interno
- el runtime estaba demasiado acoplado al entrypoint

## Estructura limpia inicial

### `desktop/config.py`

Resuelve configuracion desktop desde entorno.

### `desktop/application.py`

Orquestador principal del runtime desktop.

Responsabilidades:

- arrancar servidor local
- esperar readiness
- levantar agentes locales
- crear ventana nativa
- arrancar tray

### `desktop/services/local_server.py`

Gestiona el backend FastAPI embebido.

### `desktop/local_agents/*`

Agentes locales de bajo nivel.

Hoy:

- `HardwareAgent`
- `MonitoringAgent`

## Direccion a futuro

La desktop app deberia evolucionar hacia estas piezas:

### 1. Assistant Runtime

Core local del asistente.

### 2. Capability Bridge

Expone capacidades del equipo local al asistente:

- ficheros
- procesos
- metricas
- portapapeles
- comandos locales
- apps corporativas

### 3. Local Agents

Agentes autonomos o semi-autonomos:

- monitor local
- hardware
- diagnostico local
- skills del puesto

### 4. Window Shell

Solo la superficie nativa.

### 5. Tray / Quick Actions

Atajos y notificaciones.

## Relacion con la web

La web es la superficie.

La desktop es:

- superficie
- runtime local
- puente de capacidades

Por eso la desktop acabara siendo mas importante que una simple ventana con webview.

## Siguiente paso recomendable

1. crear un `desktop capability registry`
2. modelar permisos por capacidad local
3. definir skills locales para diagnostico del equipo
4. conectar el asistente general con esas capacidades en vez de dejar el desktop como mero contenedor
