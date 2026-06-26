# Deep Dive De Tecnologias Habituales En Empresa

Este documento define el universo tecnico que `Nexus` deberia contemplar en una empresa normal o medianamente compleja.

No esta pensado como inventario cerrado.
Esta pensado como mapa de dominios operativos para:

- clasificar alertas
- resolver activos
- elegir metodo de acceso
- definir capacidades por familia
- decidir prioridades de implementacion

## Principio base

`Nexus` no debe modelar tecnologias sueltas una a una desde el principio.

Debe modelar **dominios operativos** y, dentro de cada dominio:

- familias tecnologicas
- tipos de activo
- origenes de señal
- metodos de acceso
- capacidades de observacion
- capacidades de accion
- nivel de riesgo

## Dominios principales

### 1. Puesto de usuario

Tecnologias tipicas:

- Windows 10/11
- macOS
- Linux desktop
- navegadores
- Office / M365
- Outlook
- Teams
- antivirus / EDR
- VPN client
- impresoras locales

Tipos de activo:

- laptop
- desktop
- usuario final
- perfil de sesion

Señales habituales:

- equipo lento
- problemas de VPN
- Outlook bloqueado
- Teams sin audio
- antivirus detecta algo
- falta de espacio
- proceso colgado

Acceso habitual:

- runtime local desktop
- PowerShell
- WMI / WinRM
- scripts locales
- logs del sistema
- APIs de MDM / EDR

Capacidades de observacion:

- `desktop.metrics.read`
- `desktop.processes.read`
- `desktop.files.read`
- `desktop.network.state`
- `desktop.apps.state`
- `desktop.eventlog.read`

Capacidades de accion:

- matar proceso
- reiniciar servicio local
- vaciar cache temporal
- reconectar VPN
- abrir ticket

Prioridad Nexus:

- media

Motivo:

- da mucho valor al usuario final
- pero no es lo primero si el foco es NOC / SOC / infra

### 2. Identidad y acceso

Tecnologias tipicas:

- Active Directory
- LDAP
- Entra ID / Azure AD
- ADFS
- MFA
- SSO
- PAM
- vaults de credenciales

Tipos de activo:

- usuario
- grupo
- rol
- servicio de autenticacion
- controlador de dominio

Señales habituales:

- login fallido
- cuenta bloqueada
- MFA caido
- token expirado
- errores de federacion
- permisos inconsistentes

Acceso habitual:

- LDAP
- APIs de identidad
- PowerShell
- consolas cloud

Capacidades de observacion:

- `identity.user.lookup`
- `identity.group.lookup`
- `identity.auth.failures`
- `identity.directory.health`

Capacidades de accion:

- desbloquear cuenta
- resetear MFA
- reasignar grupo

Prioridad Nexus:

- alta

Motivo:

- casi cualquier incidencia acaba rozando identidad

### 3. Servidores Linux

Tecnologias tipicas:

- Ubuntu
- Debian
- RHEL
- CentOS
- Rocky
- AlmaLinux
- SUSE

Tipos de activo:

- host
- servicio
- daemon
- filesystem
- proceso

Señales habituales:

- CPU alta
- memoria alta
- disco lleno
- servicio caido
- errores en logs
- host no responde
- carga anomala

Acceso habitual:

- SSH
- agents
- APIs de observabilidad

Capacidades de observacion:

- `host.run_command`
- `host.read_logs`
- `service.status`
- `filesystem.usage`
- `process.list`

Capacidades de accion:

- reiniciar servicio
- limpiar temporales
- rotar logs
- desplegar parche

Prioridad Nexus:

- muy alta

Motivo:

- es la vertical mas universal y reutilizable

### 4. Servidores Windows

Tecnologias tipicas:

- Windows Server
- IIS
- servicios .NET
- Scheduled Tasks
- Event Viewer

Tipos de activo:

- host
- servicio
- pool IIS
- tarea programada

Señales habituales:

- servicio parado
- Event Log con errores
- IIS devolviendo 500
- consumo anormal
- problemas de disco

Acceso habitual:

- WinRM
- PowerShell remoting
- WMI
- APIs corporativas

Capacidades de observacion:

- `host.run_powershell`
- `service.status`
- `eventlog.read`
- `process.list`
- `iis.app_pool.status`

Capacidades de accion:

- reiniciar servicio
- reciclar app pool
- lanzar tarea

Prioridad Nexus:

- muy alta

Motivo:

- junto con Linux cubre gran parte del compute empresarial

### 5. Virtualizacion y plataforma

Tecnologias tipicas:

- VMware vSphere
- Hyper-V
- Proxmox

Tipos de activo:

- hypervisor
- cluster
- VM
- datastore
- snapshot

Señales habituales:

- datastore saturado
- VM suspendida
- host con sobrecarga
- snapshot olvidado
- migracion fallida

Acceso habitual:

- APIs de vCenter
- PowerCLI
- SDKs

Capacidades de observacion:

- `vm.describe`
- `cluster.capacity`
- `datastore.usage`
- `snapshot.list`

Capacidades de accion:

- apagar/encender VM
- consolidar snapshot
- migrar VM

Prioridad Nexus:

- alta

### 6. Contenedores y orquestacion

Tecnologias tipicas:

- Docker
- Docker Compose
- Kubernetes
- OpenShift

Tipos de activo:

- container
- image
- pod
- node
- deployment
- namespace

Señales habituales:

- contenedor caido
- restart loop
- imagen erronea
- pod pending
- healthcheck fallido
- nodo degradado

Acceso habitual:

- Docker CLI / API
- kubectl
- Kubernetes API

Capacidades de observacion:

- `container.inspect`
- `container.logs`
- `container.stats`
- `pod.describe`
- `pod.logs`
- `deployment.status`

Capacidades de accion:

- restart
- rollout undo
- scale
- cordon/drain

Prioridad Nexus:

- alta

Motivo:

- cada vez mas frecuente, pero no debe secuestrar la arquitectura

### 7. Red: switching, routing y balanceo

Tecnologias tipicas:

- Cisco IOS / IOS-XE
- Cisco Nexus
- Aruba
- Juniper
- load balancers

Tipos de activo:

- switch
- router
- interfaz
- vlan
- route
- port-channel
- FHRP

Señales habituales:

- interfaz down
- errores CRC
- flapping
- STP
- BGP caido
- latencia anomala
- MTU mismatch

Acceso habitual:

- SSH/CLI
- SNMP
- Netconf/Restconf
- vendor APIs

Capacidades de observacion:

- `switch.show_interfaces`
- `switch.show_mac_table`
- `switch.show_spanning_tree`
- `router.show_routes`
- `router.show_bgp`
- `network.latency_probe`

Capacidades de accion:

- bounce interface
- clear counters
- activar/desactivar puerto

Prioridad Nexus:

- muy alta

Motivo:

- el impacto suele ser transversal y mata media empresa cuando cae algo

### 8. Seguridad perimetral y firewalls

Tecnologias tipicas:

- Fortinet
- Palo Alto
- Check Point
- Cisco ASA / FTD
- WAF
- proxies

Tipos de activo:

- firewall
- policy
- interface
- route
- security profile
- session table

Señales habituales:

- perdida de conectividad
- deny inesperado
- session exhaustion
- HA failover
- IPS/AV bloqueando trafico

Acceso habitual:

- vendor API
- SSH/CLI
- syslog

Capacidades de observacion:

- `firewall.system_status`
- `firewall.interface_status`
- `firewall.route_table`
- `firewall.session_overview`
- `firewall.event_logs`

Capacidades de accion:

- clear session
- cambiar policy
- forzar failover

Prioridad Nexus:

- muy alta

### 9. Almacenamiento y backup

Tecnologias tipicas:

- NAS
- SAN
- NetApp
- Pure Storage
- Veeam
- Commvault

Tipos de activo:

- volumen
- cabina
- snapshot
- job de backup
- repositorio

Señales habituales:

- backup fallido
- latencia de storage
- volumen lleno
- path down
- snapshot corruption

Acceso habitual:

- vendor API
- consolas web
- SSH

Capacidades de observacion:

- `storage.volume.health`
- `storage.capacity`
- `backup.job.status`
- `backup.last_success`

Capacidades de accion:

- relanzar backup
- montar snapshot
- failover path

Prioridad Nexus:

- media-alta

### 10. Bases de datos

Tecnologias tipicas:

- SQL Server
- Oracle
- PostgreSQL
- MySQL / MariaDB
- MongoDB
- Redis

Tipos de activo:

- instancia
- base de datos
- replica
- query
- job

Señales habituales:

- conexiones agotadas
- query lenta
- bloqueo
- replica caida
- espacio insuficiente
- failover

Acceso habitual:

- SQL
- shell nativa
- APIs cloud
- SSH

Capacidades de observacion:

- `db.health`
- `db.replication.status`
- `db.top_queries`
- `db.storage.usage`

Capacidades de accion:

- matar query
- failover controlado
- relanzar replica

Prioridad Nexus:

- alta

### 11. Middleware y mensajeria

Tecnologias tipicas:

- RabbitMQ
- Kafka
- ActiveMQ
- IBM MQ
- Redis streams

Tipos de activo:

- broker
- queue
- topic
- consumer group

Señales habituales:

- backlog
- consumer caido
- lag
- cola bloqueada
- throughput anomalo

Acceso habitual:

- APIs
- CLIs
- dashboards

Capacidades de observacion:

- `mq.queue.depth`
- `mq.consumer.status`
- `mq.partition.lag`
- `mq.broker.health`

Capacidades de accion:

- reiniciar consumer
- pausar producer
- reprocesar

Prioridad Nexus:

- media-alta

### 12. Aplicaciones y servicios web

Tecnologias tipicas:

- APIs internas
- apps Java
- apps .NET
- Nginx
- Apache
- Node.js

Tipos de activo:

- servicio
- endpoint
- worker
- batch

Señales habituales:

- 5xx
- latencia alta
- timeouts
- workers caidos
- errores de negocio

Acceso habitual:

- logs
- tracing
- métricas
- SSH
- APM APIs

Capacidades de observacion:

- `app.health`
- `app.logs`
- `app.trace.lookup`
- `app.error.rate`

Capacidades de accion:

- reiniciar servicio
- toggle feature flag
- degradar funcionalidad

Prioridad Nexus:

- muy alta

### 13. Cloud publica

Tecnologias tipicas:

- AWS
- Azure
- GCP

Tipos de activo:

- VM
- LB
- security group
- managed db
- storage bucket
- serverless function

Señales habituales:

- quota
- instancia degradada
- IAM mal configurado
- servicio gestionado caido
- coste anomalo

Acceso habitual:

- SDKs
- APIs cloud
- CLI cloud

Capacidades de observacion:

- `cloud.instance.describe`
- `cloud.metrics`
- `cloud.network.policy`
- `cloud.iam.audit`

Capacidades de accion:

- reboot
- scale
- rotate role
- failover

Prioridad Nexus:

- alta

### 14. SaaS corporativo y herramientas internas

Tecnologias tipicas:

- Jira
- ServiceNow
- M365
- Salesforce
- GitHub / GitLab
- herramientas internas

Tipos de activo:

- ticket
- incidencia
- proyecto
- workflow
- usuario

Señales habituales:

- ticket atascado
- API caida
- automatizacion fallida
- integracion rota

Acceso habitual:

- REST APIs
- webhooks
- SDKs

Capacidades de observacion:

- `saas.ticket.lookup`
- `saas.workflow.status`
- `saas.integration.health`

Capacidades de accion:

- crear ticket
- actualizar estado
- reasignar
- comentar

Prioridad Nexus:

- alta

Motivo:

- es clave para cerrar el bucle operativo, aunque no sea “infra” pura

### 15. Observabilidad

Tecnologias tipicas:

- Prometheus
- Alertmanager
- Grafana
- Zabbix
- Elastic
- Splunk
- Loki
- Tempo
- Datadog

Tipos de activo:

- alerta
- metrica
- dashboard
- traza
- indice

Señales habituales:

- no llegan métricas
- alerting roto
- scraping fallido
- cardinalidad explosiva

Acceso habitual:

- APIs nativas
- queries
- webhooks

Capacidades de observacion:

- `monitoring.alerts.read`
- `monitoring.metrics.query`
- `monitoring.logs.query`
- `monitoring.traces.query`

Capacidades de accion:

- silenciar alerta
- cambiar ruta
- pausar regla

Prioridad Nexus:

- fundacional

Motivo:

- sin esta capa el sistema no ve nada

## Como diversificar la arquitectura

La diversificacion buena no es “soportar mas cosas”.

La diversificacion buena es separar:

### 1. Dominio tecnico

Ejemplos:

- compute
- network
- security
- storage
- middleware
- app
- cloud
- saas

### 2. Familia tecnologica

Ejemplos:

- `compute.linux`
- `network.switch.cisco`
- `network.firewall.fortinet`
- `cloud.aws`

### 3. Metodo de acceso

Ejemplos:

- SSH
- WinRM
- vendor API
- SNMP
- REST
- CLI
- SDK
- MCP

### 4. Capacidad

Ejemplos:

- observar estado
- leer logs
- consultar rutas
- ver top procesos
- reiniciar servicio
- abrir ticket

## Prioridad real para Nexus

Si construimos por impacto y reutilizacion, yo haria este orden:

### Tier 0

- observabilidad
- ticketing
- identidad minima

### Tier 1

- servidores Linux
- servidores Windows
- aplicaciones y servicios web
- Docker / Kubernetes

### Tier 2

- switches Cisco
- firewalls Fortinet
- cloud publica
- bases de datos

### Tier 3

- storage
- backup
- middleware
- puesto de usuario

## Primera taxonomia objetivo para Nexus

La primera taxonomia util de verdad deberia quedar asi:

- `identity.*`
- `compute.linux`
- `compute.windows`
- `virtualization.*`
- `container.docker`
- `container.kubernetes`
- `network.switch.*`
- `network.router.*`
- `network.firewall.*`
- `storage.*`
- `database.*`
- `middleware.messaging.*`
- `app.service.*`
- `cloud.aws.*`
- `cloud.azure.*`
- `cloud.gcp.*`
- `saas.*`
- `observability.*`

## Lo que deberiamos sacar de aqui

Este deep dive nos sirve para decidir tres cosas:

1. que familias son core en el producto
2. que adaptadores hay que construir primero
3. que habilidades debe tener JAINA para cada dominio

## Conclusión

Antes de seguir enchufando tecnologias una a una, `Nexus` necesita este mapa mental:

- que mundos existen
- como se parecen entre si
- como se accede a ellos
- que señales producen
- y que capacidades comunes podemos reutilizar

Ese es el paso correcto para diversificar sin convertir el sistema en una coleccion de hacks.
