# Open-Nexus Product Direction

## Que es Open-Nexus

Open-Nexus es la aplicacion de escritorio ejecutable de Nexus.

No es un dashboard.
No es una web empaquetada como si fuera producto.
No es un panel para vender.

Es el puesto de trabajo local desde el que el usuario habla con Nexus, lanza tareas, diagnostica infraestructura, coordina agentes y opera el negocio.

## Inspiracion correcta

La inspiracion valida no es una SPA cualquiera.

La referencia correcta es:

- Open Interpreter
- OpenCode
- asistentes locales que arrancan como herramienta de trabajo real

De ahi sale la direccion:

- shell primero
- runtime local persistente
- capacidades reales
- instalacion simple
- posibilidad de empaquetado en ejecutable

## Como queda dividido

### 1. Engine

`OpenNexusEngine`

Responsabilidad:

- recibir la orden del usuario
- resolver skill
- delegar en el coordinador Nexus
- guardar historial reciente

Archivo:

- `C:\DEV\Nexus-UI\desktop\opennexus\engine.py`

### 2. Shell

`OpenNexusShell`

Responsabilidad:

- interfaz conversacional local
- comandos internos
- mostrar skill detectado y respuesta

Archivo:

- `C:\DEV\Nexus-UI\desktop\opennexus\shell.py`

### 3. Packaging

Responsabilidad:

- convertir el shell en ejecutable
- preparar instalacion local repetible

Archivos:

- `C:\DEV\Nexus-UI\build\OpenNexus.spec`
- `C:\DEV\Nexus-UI\scripts\build_open_nexus.ps1`
- `C:\DEV\Nexus-UI\scripts\install_open_nexus_windows.ps1`

## Que se aprovecha del Nexus actual

- llm router
- coordinador
- skills compartidos
- runtime desktop
- conectores futuros de correo, CRM y operaciones

## Que no debe mandar

La web ya no debe ser la pieza central del producto desktop.

Puede existir como:

- panel de soporte
- consola secundaria
- puente de transicion

Pero el producto bueno es:

- ejecutable
- instalable
- local
- orientado a trabajo diario

## Siguiente horizonte

Open-Nexus debe crecer asi:

1. shell robusto
2. persistencia local de configuracion
3. perfiles de proveedor LLM
4. correo y CRM desde runtime local
5. adaptadores operativos
6. agentes autonomos de negocio y operaciones
