# REMOTE INFRA DIAGNOSTIC 2026-05-29

## Resumen ejecutivo

El servidor remoto `llmpro` está sano y sirve bien como backend de orquestación y routing.

No sirve para inferencia local de modelos:

- no tiene GPU
- no tiene stack de serving LLM preparado
- y no merece la pena forzarlo

Sí sirve muy bien para:

- cerebro remoto ligero
- router de mensajes
- registro de proveedores LLM
- invocación controlada de `n8n`
- observabilidad y trazabilidad

## Acceso y sistema

- Host LAN principal: `192.168.1.150`
- Host adicional: `10.1.99.128`
- SSH: OK
- Usuario verificado: `angel`
- OS: `Ubuntu 24.04.4 LTS`
- Uptime en revisión: `3h+`

## Capacidad de máquina

- CPU: `8 vCPU`
- Modelo: `11th Gen Intel i5-11320H`
- RAM total: `15 GiB`
- RAM disponible: `13 GiB`
- Swap: `4 GiB`
- Disco raíz: `98 GiB`
- Disco libre: `82 GiB`
- GPU: `no-gpu`

## Servicios y runtime disponible

- `n8n` activo como servicio `systemd`
- `n8n` escuchando en `0.0.0.0:5678`
- `Node.js v20.20.2`
- `npm 10.8.2`
- `Python 3.12.3`
- `git` y `curl` disponibles

## Red y exposición

Puertos relevantes abiertos:

- `22/tcp` SSH
- `5678/tcp` n8n

No se observan `80/443` activos.

Esto significa:

- no hay reverse proxy preparado
- no hay TLS local listo
- y cualquier nuevo servicio HTTP que abramos será otro puerto más salvo que montemos `nginx`

## Salida a Internet

La salida a Internet parece correcta.

Lo sabemos porque:

- `openrouter.ai` respondió `403`
- `api.groq.com` respondió `403`
- `generativelanguage.googleapis.com` respondió `404`

Eso no es un fallo de red.
Es respuesta HTTP válida del destino.

Conclusión:

- el servidor sí puede llegar a proveedores LLM externos

## Seguridad / firewall

No se ha podido confirmar `ufw` activo.

Resultado actual:

- `ufw-unavailable`

Eso puede significar:

- no está instalado
- no está configurado
- o el usuario actual no lo puede consultar sin privilegios

Conclusión prudente:

- no debemos asumir firewall local bien cerrado

## n8n actual

Se ha confirmado este servicio:

- unit: `n8n.service`
- user: `angel`
- host: `0.0.0.0`
- port: `5678`
- protocol: `http`
- cookie secure: `false`
- editor base URL: `http://192.168.1.150:5678`

Lectura:

- para LAN y pruebas está bien
- para exposición más seria no está endurecido

## Hallazgo importante: MicroK8s

La máquina tiene `microk8s` instalado y varios servicios activos:

- `containerd`
- `kubelite`
- `cluster-agent`
- `k8s-dqlite`

También hay puertos compatibles con control-plane:

- `10250`
- `10257`
- `10259`
- `16443`
- `25000`

Esto importa por dos motivos:

1. La máquina ya tiene complejidad oculta.
2. Montar otra cosa “rápida” sobre Kubernetes puede parecer tentador, pero aumenta el riesgo operativo.

## Diagnóstico de riesgo

### Riesgo bajo

Montar un servicio nuevo en el home del usuario `angel`, con:

- `python3 -m venv`
- `systemd`
- puerto nuevo interno

### Riesgo medio

Montar `nginx` delante y exponer otro servicio HTTP con reverse proxy.

### Riesgo alto

Meter el cerebro remoto en `microk8s` desde ya.

No porque no se pueda, sino porque:

- todavía no sabemos quién lo está usando
- no necesitamos esa complejidad
- y queremos evitar “movidas”

## Qué podemos meter sin liarla

### Sí metería ya

- un servicio `FastAPI` ligero
- un `venv` propio
- configuración por `.env` o YAML local
- `systemd` unit separada
- logs a fichero
- healthcheck simple

### No metería todavía

- modelos locales
- Kubernetes para esta pieza
- varios servicios nuevos a la vez
- una base de datos adicional si no hace falta
- proxy público o TLS si sigue siendo solo LAN

## Arquitectura mínima recomendada

### Pieza 1

`open-nexus-brain`

Responsabilidad:

- recibir peticiones del desktop
- enrutar mensajes
- seleccionar proveedor LLM
- llamar a herramientas
- invocar `n8n` si toca

### Pieza 2

`n8n`

Responsabilidad:

- ejecutar flows concretos
- no decidir
- no almacenar la lógica principal

### Pieza 3

Proveedores externos LLM

Responsabilidad:

- inferencia

## Mi recomendación práctica

Si no quieres verte en líos:

1. no uses `microk8s` para esta primera versión
2. no intentes servir modelos en local
3. monta un solo servicio Python remoto
4. deja `n8n` como herramienta detrás
5. usa proveedores externos por API

## Qué decidir antes de tocar modelos

Solo faltan estas decisiones:

- proveedor primario
- proveedor de fallback
- formato de API objetivo
- si queremos un endpoint interno único tipo OpenAI-compatible

## Siguiente paso

Hablar de modelos y, con esa decisión, montar:

- registry de proveedores
- perfiles de modelo
- router de mensajes
- endpoint único del cerebro remoto
