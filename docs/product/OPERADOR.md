# Pestana Operador

## Objetivo

`Operador` es la superficie principal para IA agentica operacional dentro del desktop.
Debe servir para investigar, priorizar, explicar y coordinar acciones sobre observabilidad, incidencias y accesos rapidos.

## Ruta y archivos

- ruta UI: `/nexus-v1`
- template: [nexus_v1.html](C:\DEV\Nexus-UI\products\desktop\ui\templates\nexus_v1.html)
- cliente JS: [nexus_v1.js](C:\DEV\Nexus-UI\products\desktop\ui\static\js\nexus_v1.js)
- estilos: [nexus_v1.css](C:\DEV\Nexus-UI\products\desktop\ui\static\css\nexus_v1.css)

## Bloques actuales

### Hero superior

Incluye:

- `Acceso rapido` con un unico campo de IP/host
- boton `SSH`
- boton `RDP`
- bloque `Recoleccion`
- `Estado`
- `Ultimo refresco`
- selector `Auto refresh`
- refresco manual

### Bloque principal izquierdo

Se divide en:

- chat del supervisor/coordinator
- chips de prompts rapidos
- composer de mensaje
- `Bus agentico` visual para marketing y explicacion de orquestacion

### Espacio derecho

- reservado como `growth space`
- pensado para crecer sin redisenar la pagina otra vez

## Integraciones y endpoints

### Operativa visual

El frontend usa:

- `/api/nexus/monitoring/collectors`
- `/api/nexus/audit`
- `/api/nexus/incidents`
- `/api/nexus/agents/runs`
- `/api/nexus/chat`

### Relacion con Sales

`Operador` no ejecuta la prospeccion comercial, pero ya debe entender su trazabilidad.

Contexto actual:

- `Sales` tiene una capa agentica propia de 7 agentes para proteger brief, refinar, planificar fuentes, construir queries, ejecutar discovery, cualificar y preparar CRM
- la configuracion de esos prompts vive en `Configuracion > Prompting`, grupo `sales`
- la ejecucion comercial sigue siendo dominio de `Sales`, no de `Operador`

Lo que `Operador` si debe poder hacer o explicar:

- leer que un run comercial usa un `source_plan`
- distinguir fuente primaria y fallback
- explicar que el comportamiento de IA comercial depende de prompts vivos
- derivar al panel de `Configuracion` cuando el ajuste sea de prompt y no de observabilidad

Endpoints utiles para esa lectura:

- `/api/nexus/prospecting/runs/{id}`
- `/api/nexus/prospecting/runs/{id}/logs`

### Configuracion de links de observabilidad

Para pintar los bullets superiores como enlaces reales usa:

- `/api/desktop/operator/integrations`

Eso hace que `Prometheus`, `Grafana` y `Alertmanager` salgan desde configuracion viva y no hardcodeados.

### RDP

El cliente RDP se lanza via:

- `/api/desktop/operator/rdp`

Comportamiento actual:

- valida IP
- abre `mstsc.exe` contra esa IP
- registra inicio y fin de sesion en logs del desktop

## Reglas funcionales actuales

- `Operador` no debe depender de valores hardcodeados de observabilidad
- la parte de IA tiene que acabar explicando decisiones, no solo respondiendo texto
- esta pantalla esta pensada para ser densa y crecer mucho

## Estado de diseno esperado

La intencion actual del producto es:

- hero compacto
- chat como bloque dominante
- bus agentico ocupando la franja inferior del bloque izquierdo
- espacio libre a la derecha para futuras piezas operativas

## Notas de futuro

Cuando se siga evolucionando esta pestana, los siguientes bloques naturales son:

- acceso SSH real
- acceso RDP real con trazabilidad completa
- supervisor con delegacion a agentes
- housekeeper / memoria / guardrail
- paneles de contexto operativo en la zona derecha
