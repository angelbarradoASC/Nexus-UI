# Open-Nexus Reverse Engineering

## Punto de partida real

Se ha descargado el repositorio oficial de Open Interpreter en:

- `C:\DEV\Nexus-UI\vendor\open-interpreter`

No habia una copia util previa dentro de Nexus. Lo que habia eran referencias y notas de arquitectura, pero no una base integrada para producto.

## Que hace Open Interpreter de verdad

Open Interpreter no nace como "web app". Nace como:

- producto CLI primero
- runtime central (`OpenInterpreter`) que orquesta LLM + herramientas + ejecucion
- interfaz terminal separada del core
- perfiles para configurar proveedores, modos y comportamiento
- instaladores sencillos por sistema operativo

Las piezas que importan son:

- `interpreter/core/core.py`
- `interpreter/terminal_interface/start_terminal_interface.py`
- `interpreter/terminal_interface/profiles/*`
- `installers/oi-windows-installer.ps1`

## Lo que merece la pena copiar

Para Open-Nexus, lo valioso no es el branding ni los prompts.
Lo valioso es:

- separar motor, shell e instalacion
- tratar el producto como ejecutable instalable
- tener un runtime local persistente
- enrutar por capacidades antes de ejecutar
- usar perfiles/configuracion para proveedores y modos
- mantener una experiencia conversacional de shell, no una pantalla web obligatoria

## Lo que no nos interesa copiar tal cual

- telemetry del proyecto original
- prompts genericos para "AI OS"
- local model setup como supuesto principal
- toolset demasiado abierto y poco orientado a empresa
- decisiones de UX centradas en el terminal publico de OI

## Decision para Open-Nexus

Open-Nexus debe quedar estructurado asi:

1. `OpenNexusEngine`
   - runtime local
   - skill routing
   - puente al coordinador Nexus

2. `OpenNexusShell`
   - consola de trabajo instalable
   - interfaz parecida al espiritu de Open Interpreter

3. `build/install`
   - pipeline de empaquetado
   - instalador Windows

4. `capability adapters`
   - infraestructura
   - correo
   - CRM
   - diagnostico operativo

## Implementacion iniciada

Se ha creado una primera base propia:

- `C:\DEV\Nexus-UI\desktop\opennexus\engine.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\shell.py`
- `C:\DEV\Nexus-UI\desktop\open_nexus_main.py`
- `C:\DEV\Nexus-UI\build\OpenNexus.spec`
- `C:\DEV\Nexus-UI\scripts\build_open_nexus.ps1`
- `C:\DEV\Nexus-UI\scripts\install_open_nexus_windows.ps1`

## Estado honesto

Esto todavia no es el producto final.
Pero ya deja de depender conceptualmente de "abrir una web" y empieza a existir como shell ejecutable con pipeline de build e instalacion.

El siguiente paso correcto es endurecer:

- empaquetado real
- persistencia local de configuracion
- integracion con correo y CRM desde el shell
- y luego interfaz nativa mas rica si hace falta
