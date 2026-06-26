# Arquitectura Canónica

> Documento de referencia para hablar del sistema sin mezclar nombres, capas ni responsabilidades.
> Si este archivo contradice otros borradores, este archivo gana hasta que se actualice explícitamente.

## Idea central

El producto no es "solo un chat" ni "solo una app de escritorio". Es una plataforma propia para ejecutar tareas con IA, conectada a herramientas internas y accesos locales, con capacidad para:

- conversar con el usuario
- diagnosticar y resolver incidencias
- usar herramientas internas como Jira, ServiceNow o MCPs locales
- ejecutar acciones en el equipo local o en la red corporativa
- aprender el uso correcto de cada herramienta mediante entrenamiento específico

## Piezas principales

### 1. NEXUS

NEXUS es el sistema central.

Tiene dos caras:

- **NEXUS Web**: la superficie web y el backend principal
- **NEXUS Desktop**: la aplicación instalable en el PC, orientada a uso local y accesos de máquina

NEXUS no es "la IA". NEXUS es la plataforma que recibe entradas, orquesta tareas, expone APIs, persiste datos y ejecuta flujos.

La ruta objetivo de implementación para esta arquitectura vive en `app/nexus/`.

NEXUS también incluye el conjunto de agentes de monitorización:

- recibe métricas y alertas
- consulta sistemas de observabilidad
- expone API para ingestión y consulta
- actúa sobre Alertmanager cuando hace falta silenciar, clasificar o escalar
- mantiene trazabilidad de incidentes y acciones automáticas

### 2. JAINA

JAINA es el motor de IA / razonamiento.

Su función es interpretar, decidir, redactar y ayudar a resolver.

JAINA se usa para:

- clasificar intención
- extraer parámetros
- decidir qué herramienta o agente usar
- redactar respuestas
- razonar cuando una tarea necesita más contexto o más complejidad

JAINA puede operar como motor local, como motor servidor o como capa de razonamiento superior, pero siempre como inteligencia, no como simple UI.

### 3. Hive Mind

Hive Mind es el motor de correlación y minería indirecta.

No está para responder al usuario de forma directa en el camino crítico.

Su trabajo es:

- analizar datos aparentemente no relacionados
- encontrar patrones y causas probables
- correlacionar incidencias, telemetría, tickets y señales de distintos sistemas
- alimentar a JAINA o a NEXUS con hallazgos útiles

Hive Mind vive en background y trabaja por lotes o por ingesta de datos.

## Módulo de incidencias y alarmas

El sistema incluye un módulo para recibir alarmas o incidencias desde una API expuesta.

Ese módulo debe poder:

- recibir eventos externos por API o webhook
- normalizar la alarma
- decidir si puede autocorregirse
- diagnosticar con los accesos locales o MCP configurados
- ejecutar la reparación posible
- abrir o actualizar tickets si hace falta
- dejar trazabilidad de lo que hizo y por qué

Este módulo no es un adorno. Es una pieza núcleo del sistema.

## Monitorización

NEXUS debe tener una capacidad real de monitorización operativa, no solo visualización.

### Qué hace

- consume alertas desde Prometheus Alertmanager
- consulta Prometheus para contexto de métricas
- mantiene un API propia para ingestión de métricas y alertas desde agentes locales
- permite acciones operativas como silencios, confirmaciones y derivación de incidencias
- puede activar flujos de diagnóstico automático cuando una alerta lo justifica

### Qué significa en la práctica

NEXUS no se limita a mostrar alertas en pantalla. Es el punto de coordinación entre:

- observabilidad externa
- agentes locales
- diagnóstico
- reparación
- ticketing

### Alcance realista de la primera versión

- leer alertas de Alertmanager
- consultar métricas de Prometheus
- recibir telemetría propia vía API
- mostrar estado y contexto al usuario
- permitir una primera respuesta operativa controlada

### Alcance posterior

- correlación automática de alertas
- runbooks con pasos de reparación
- deduplicación inteligente
- aprendizaje de falsos positivos
- acciones autónomas más agresivas con confirmación o política

## Integración con herramientas internas

NEXUS y JAINA no "adivinan" cómo usar Jira, ServiceNow o herramientas internas.

El sistema se apoya en entrenamiento y configuración específicos para cada herramienta:

- qué campos rellenar
- cómo redactar el ticket
- qué priorización usar
- qué validaciones aplicar
- cuándo escalar en vez de ejecutar

La idea es que la IA aprenda el protocolo operativo de cada herramienta, no solo su nombre.

## MCP y accesos locales

Los MCPs y los accesos locales son la vía de ejecución y diagnóstico sobre sistemas internos.

Regla práctica:

- la IA decide
- NEXUS orquesta
- MCPs y conectores ejecutan

No queremos que el modelo "toque infra" por su cuenta sin una capa de control.

## Flujo mental correcto

```text
Usuario o sistema externo
  -> NEXUS recibe la entrada
  -> JAINA razona / clasifica / propone
  -> NEXUS selecciona agente, skill, MCP o flujo
  -> ejecución local o remota controlada
  -> respuesta, ticket o corrección
  -> trazabilidad y aprendizaje
```

Para casos de incidentes:

```text
Alarma/API
  -> NEXUS
  -> diagnóstico
  -> ejecución de reparaciones posibles
  -> ticket si hace falta
  -> registro de auditoría
```

## Qué va primero y qué va después

### Camino crítico

- recepción de mensajes
- clasificación
- diagnóstico
- ejecución de acciones
- trazabilidad

### Camino no crítico

- correlación avanzada
- minería histórica
- reporting complejo
- análisis entre sistemas

## Resumen corto

- **NEXUS**: plataforma central, web y desktop, orquesta y ejecuta
- **NEXUS Monitoring**: agentes y API para observabilidad, alertas y respuesta operativa
- **JAINA**: motor de IA y razonamiento
- **Hive Mind**: correlación y minería de datos
- **Incidencias**: módulo núcleo que entra por API y puede diagnosticar y reparar
- **MCPs**: ejecución controlada sobre infra y accesos locales

## Regla de oro

Si algo decide, razona o redacta, tiende a ser JAINA.
Si algo recibe, orquesta, expone APIs o ejecuta el flujo, tiende a ser NEXUS.
Si algo encuentra relaciones ocultas entre datos, tiende a ser Hive Mind.
