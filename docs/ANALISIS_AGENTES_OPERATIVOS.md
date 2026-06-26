# Analisis De Agentes Operativos

## Idea central

`Nexus` no debe estar construido alrededor de `Docker`.

`Docker` nos sirve como entorno de pruebas porque lo tenemos a mano, pero la arquitectura real debe asumir desde el principio que una alerta puede venir de:

- switches
- routers
- firewalls
- servidores Linux
- servidores Windows
- contenedores
- Kubernetes
- clouds publicas
- bases de datos
- balanceadores
- herramientas SaaS

La pregunta correcta no es:

- `que comando ejecuto para esta alerta`

La pregunta correcta es:

- `que tecnologia esta afectada`
- `que activo concreto esta implicado`
- `por que metodo de acceso puedo investigar`
- `que siguiente accion de observacion tiene mas sentido`

Y esa cuarta pregunta es la que debe decidir el LLM.

## Donde esta hoy el sistema

Hoy `Nexus` ya puede:

- recibir alertas
- convertirlas en incidentes
- asignar runbooks basicos
- auditar acciones
- mostrar actividad en interfaz

Pero todavia no puede operar de verdad porque falta el nucleo inteligente:

- clasificacion tecnologica
- resolucion de activo
- resolucion de metodo de acceso
- bucle de investigacion iterativo guiado por LLM
- ejecucion real con validacion posterior

## Error de arquitectura que hay que evitar

No debemos construir:

- `alerta -> runbook fijo -> comando fijo`

Eso es automatizacion tradicional.

Tampoco debemos construir:

- `alerta -> shell libre`

Eso es peligroso y poco gobernable.

Lo correcto es:

- `alerta -> clasificacion -> contexto -> LLM investigador -> accion propuesta -> policy -> ejecucion -> nueva observacion -> LLM`

## Principio rector

El LLM no debe recibir una alerta y producir una reparacion inmediata.

Debe comportarse como un operador bueno:

1. formula una hipotesis
2. decide que evidencia necesita
3. elige una capacidad disponible
4. observa el resultado
5. reinterpreta la situacion
6. decide el siguiente paso
7. para cuando ya sabe suficiente o no tiene permiso para avanzar

## Cadena logica correcta

### 1. Alert Intake

Recibe la señal y la normaliza.

Datos minimos:

- `source_system`
- `alert_name`
- `severity`
- `labels`
- `annotations`
- `fingerprint`
- `raw_payload`

### 2. Technology Classification

Este es el primer paso importante.

La alerta debe clasificarse en una taxonomia tecnica comun.

Ejemplo de familias:

- `network.switch`
- `network.router`
- `network.firewall`
- `compute.linux`
- `compute.windows`
- `compute.vmware`
- `container.docker`
- `container.kubernetes`
- `cloud.aws`
- `cloud.azure`
- `cloud.gcp`
- `platform.database`
- `platform.web`
- `platform.messaging`

Este paso usa:

- labels
- origen del sistema de alertas
- tags
- convenciones de nombre
- inventario
- CMDB
- y, si hace falta, ayuda del LLM

### 3. Target Resolution

Una vez sabemos la familia tecnologica, toca identificar el activo concreto.

Ejemplos:

- `srv-app-01`
- `fw-core-01`
- `nexus-worker`
- `payments-api-pod-abc`
- `i-0a12b34`
- `redis-prod-01`

Sin este paso, el agente no sabe sobre que esta pensando realmente.

### 4. Access Resolution

Despues hay que decidir como se accede.

La tecnologia y el metodo de acceso no son lo mismo.

Ejemplos:

- `compute.linux` -> `ssh`
- `container.docker` -> `docker_api`
- `network.firewall` -> `ssh` o `vendor_api`
- `cloud.aws` -> `sdk_api`
- `platform.database` -> `sql` o `ssh`

Esta capa debe devolver:

- `access_type`
- `connector_name`
- `credential_profile`
- `allowed_capabilities`

### 5. Context Builder

Prepara el caso para el agente LLM.

El LLM no debe arrancar ciego.

Debe recibir:

- alerta original
- resumen del incidente
- taxonomia detectada
- activo resuelto
- metodo de acceso disponible
- runbook orientativo
- historial parecido
- restricciones de policy
- capacidades disponibles

### 6. Investigation Loop

Este es el nucleo de inteligencia real.

El LLM itera.

Cada iteracion produce:

- hipotesis actual
- objetivo de observacion
- capacidad a usar
- parametros
- motivo
- criterio de interpretacion

No produce directamente un comando shell crudo por defecto.

Produce una intencion operativa sobre una capacidad.

Ejemplo:

- `quiero inspeccionar el estado del contenedor`
- `quiero leer los ultimos logs`
- `quiero consultar la metrica de CPU sostenida`
- `quiero revisar el estado de una interfaz`

Luego el conector traduce eso a la operacion concreta.

### 7. Policy Gate

El LLM propone.

La policy decide si:

- esa capacidad esta permitida
- ese parametro entra dentro de limites
- esa accion es solo de lectura
- esa accion necesita aprobacion
- esa accion esta prohibida

### 8. Execution

El ejecutor no piensa.

Solo:

- invoca el conector correcto
- captura evidencia
- devuelve resultado estructurado

### 9. Verification

Despues de ejecutar, hay que comprobar:

- si el objetivo ha cambiado de estado
- si la alerta sigue activa
- si aparecio un efecto secundario
- si el incidente puede resolverse

## El papel real de los runbooks

Los runbooks no deben ser recetas que dicten un comando fijo.

Deben servir como:

- pista de por donde empezar
- lista de señales relevantes
- limites operativos
- recomendaciones
- criterios de escalado

O sea:

- el runbook orienta
- el LLM investiga
- la policy limita

## La abstraccion correcta: capacidades

La unidad de decision del LLM no debe ser el comando literal.

Debe ser una capacidad.

### Ejemplos de capacidades

Para Linux por SSH:

- `host.run_command`
- `host.read_logs`
- `service.status`
- `service.restart`
- `file.read`

Para Docker:

- `container.list`
- `container.inspect`
- `container.logs`
- `container.exec`
- `container.restart`

Para red:

- `device.show_interfaces`
- `device.show_cpu`
- `device.show_logs`
- `device.show_routes`

Para cloud:

- `instance.describe`
- `instance.metrics`
- `instance.reboot`
- `resource.tags`

El LLM decide:

- que capacidad usar
- en que orden
- con que parametros
- segun la evidencia anterior

## Arquitectura de agentes recomendada

### 1. Intake Agent

Recibe la alerta y abre el caso.

### 2. Technology Classification Agent

Clasifica la familia tecnica.

### 3. Target Resolution Agent

Identifica el activo real afectado.

### 4. Access Resolution Agent

Decide el metodo de acceso disponible.

### 5. Investigation Agent

Es el cerebro.

Itera:

- hipotesis
- observacion
- reinterpretacion

### 6. Planning Agent

Decide si:

- seguir investigando
- contener
- reparar
- escalar
- pedir aprobacion

### 7. Execution Agent

Ejecuta una capacidad aprobada.

### 8. Verification Agent

Valida si el problema sigue o no.

### 9. Memory Agent

Guarda:

- patrones de investigacion utiles
- resoluciones efectivas
- condiciones de fallo

## Ejemplo correcto de flujo

### Caso: alerta de CPU alta

La alerta entra con:

- `alertname=HighCPU`
- `instance=srv-app-01`
- `source_system=prometheus`

El sistema hace:

1. clasifica como `compute.linux`
2. resuelve target `srv-app-01`
3. resuelve acceso `ssh`
4. prepara contexto
5. el LLM decide consultar metricas y logs
6. ve que la CPU alta viene de un proceso puntual
7. decide seguir observando y no reiniciar
8. documenta conclusion

Aqui no hay una regla fija `HighCPU -> restart`.

### Caso: alerta de contenedor caido

En laboratorio, hoy lo probaremos con Docker:

1. clasifica como `container.docker`
2. resuelve target `nexus-worker`
3. resuelve acceso `docker_api`
4. el LLM pide inspeccion
5. luego logs
6. luego decide si reinicio, escalado o no actuacion

Pero esto no hace de Docker la arquitectura.

Hace de Docker el primer backend real de acceso para probar la arquitectura.

## Que significa usar Docker para pruebas

Usar Docker para pruebas debe significar:

- probar la cadena general con una tecnologia concreta

No:

- construir la arquitectura alrededor de Docker

El backend de Docker debe ser:

- el primero
- no el principal

## Vertical slice correcta

La primera vertical slice deberia llamarse asi:

- `investigation loop v1`

Y su primer backend real seria:

- tecnologia soportada: `container.docker`

Despues podriamos añadir:

- `compute.linux`
- `network.firewall`
- `cloud.aws`

sin romper la logica general.

## Mi lectura honesta del sistema

Lo que ya esta bien:

- recepcion de alertas
- incidente
- auditoria
- UI operativa inicial

Lo que falta para que se note inteligencia real:

- clasificacion por tecnologia
- resolucion de target
- resolucion de acceso
- agente de investigacion iterativo
- conectores operativos por capacidades
- verificacion post-accion

## Orden de construccion que recomiendo

### Fase 1

- taxonomia tecnologica
- modelo de `target`
- modelo de `access method`

### Fase 2

- `InvestigationLoop`
- `PolicyGate`
- `CapabilityAdapter`

### Fase 3

- backend `Docker` como primer laboratorio
- caso completo `ContainerDown`

### Fase 4

- backend `SSH`
- casos sobre Linux real

### Fase 5

- fuentes nuevas:
  - `Zabbix`
  - `network`
  - `cloud`

## Conclusión

La potencia real del LLM no esta en mapear alertas a comandos.

Esta en:

- investigar
- reinterpretar
- decidir el siguiente paso

Pero para que eso sea util y no peligroso, antes debemos darle:

- una taxonomia comun
- un modelo de activos
- un modelo de acceso
- capacidades bien definidas
- policy
- ejecucion estructurada

Ese es el camino correcto.
