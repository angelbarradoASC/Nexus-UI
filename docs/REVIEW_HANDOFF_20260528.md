# Review Handoff 2026-05-28

## Objetivo de este handoff

Este paquete se prepara para que otra IA o revisor tecnico pueda inspeccionar el estado real de Nexus sin depender de contexto oral previo.

La intencion es que el revisor entienda:

- que problema de producto se esta intentando resolver
- que partes estaban naciendo como web
- por que se ha pivotado hacia una aplicacion de escritorio tipo Open Interpreter
- que codigo nuevo existe ya
- que riesgos, huecos y decisiones siguen abiertos

## Resumen ejecutivo

El proyecto venia empujando una superficie web operativa en `app/nexus` con chat, monitorizacion, correo, outreach y CRM.

Ese camino sirvio para validar piezas, pero el producto deseado no es una web. El objetivo real es una aplicacion de escritorio instalable, local-first, con runtime propio, agentes y capacidades operativas. La referencia conceptual que se ha tomado para reorientar el producto es Open Interpreter.

Por eso se ha iniciado una nueva linea llamada `Open-Nexus`, con estos pasos ya dados:

- descarga del repo oficial de Open Interpreter en `vendor/open-interpreter`
- analisis de su arquitectura real
- definicion de la direccion de producto desktop
- creacion de una base inicial de shell local
- preparacion de build e instalacion para Windows

## Lo que ya existia y sigue siendo importante

### Capa Nexus web y APIs

Ruta principal:

- `C:\DEV\Nexus-UI\app\nexus`

Capacidades que ya existian:

- chat general
- monitorizacion y recolectores
- incidentes
- auditoria
- outreach comercial
- integracion Thunderbird
- integracion CRM interno
- editor de prompts

Documentos clave:

- `C:\DEV\Nexus-UI\docs\ARQUITECTURA_CANONICA.md`
- `C:\DEV\Nexus-UI\docs\NEXUS_V1.md`
- `C:\DEV\Nexus-UI\docs\ORQUESTACION_AGENTES.md`
- `C:\DEV\Nexus-UI\docs\ROADMAP_PRODUCCION.md`

### Integraciones comerciales ya validadas

- correo de outreach
- lectura real de Thunderbird
- CRM interno basado en `assets-web-api`

### Prompt management

Ya existe sistema de prompts editables:

- `C:\DEV\Nexus-UI\app\nexus\prompts`
- pagina web de edicion: `/nexus-prompts`

## El pivot importante

La decision nueva es que la web deja de ser la pieza central del producto desktop.

Se mantiene como:

- superficie de soporte
- consola secundaria
- puente temporal

Pero el producto principal pasa a ser `Open-Nexus`, un shell local y posteriormente un ejecutable instalable.

## Codigo nuevo de Open-Nexus

### Motor y shell

- `C:\DEV\Nexus-UI\desktop\opennexus\engine.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\shell.py`
- `C:\DEV\Nexus-UI\desktop\open_nexus_main.py`

### Build e instalacion

- `C:\DEV\Nexus-UI\build\OpenNexus.spec`
- `C:\DEV\Nexus-UI\scripts\build_open_nexus.ps1`
- `C:\DEV\Nexus-UI\scripts\install_open_nexus_windows.ps1`

### Puente temporal en la app actual

- `C:\DEV\Nexus-UI\app\templates\open_nexus.html`
- `C:\DEV\Nexus-UI\app\static\css\open_nexus.css`
- `C:\DEV\Nexus-UI\app\static\js\open_nexus.js`
- ruta `/open-nexus`

### Cambios de arranque desktop

- `C:\DEV\Nexus-UI\desktop\config.py`
- `C:\DEV\Nexus-UI\desktop\application.py`
- `C:\DEV\Nexus-UI\desktop\tray.py`

## Open Interpreter descargado para ingeniería inversa

Ruta:

- `C:\DEV\Nexus-UI\vendor\open-interpreter`

Piezas inspeccionadas:

- `interpreter/core/core.py`
- `interpreter/terminal_interface/start_terminal_interface.py`
- `installers/oi-windows-installer.ps1`
- estructura de `profiles`

Lectura principal:

- Open Interpreter nace shell-first
- separa runtime, terminal interface y perfiles
- ofrece instaladores simples
- no depende conceptualmente de una web como producto

## Documentacion nueva relevante

- `C:\DEV\Nexus-UI\docs\OPEN_NEXUS_REVERSE_ENGINEERING.md`
- `C:\DEV\Nexus-UI\docs\OPEN_NEXUS_PRODUCT.md`
- `C:\DEV\Nexus-UI\docs\OPEN_NEXUS_BUILD_INSTALL.md`
- `C:\DEV\Nexus-UI\docs\WEB_TO_OPEN_NEXUS_FEATURE_MAP.md`
- `C:\DEV\Nexus-UI\docs\OPEN_NEXUS_MIGRATION_PLAN.md`

## Estado honesto del proyecto

### Lo que ya esta bien orientado

- routing local de skills
- runtime desktop compartido
- conectores y casos reales en web
- integracion de correo y CRM validada
- sistema de prompts editable
- base inicial de shell desktop
- build e instalacion bosquejados

### Lo que todavia no esta cerrado

- `Open-Nexus` aun no es el ejecutable final distribuible
- el shell es todavia inicial
- hay una mezcla temporal entre desktop real y puente web
- falta cerrar experiencia de usuario puramente desktop
- falta probar build real de PyInstaller extremo a extremo

## Riesgos y deuda

- riesgo de seguir metiendo funcionalidad nueva en la web por inercia
- riesgo de duplicar logica entre web y desktop
- riesgo de empaquetado roto si no se cierran dependencias
- riesgo de UX confusa durante la transicion

## Recomendacion de siguiente paso

Si este proyecto lo revisa otra IA, lo mas util no es que implemente a ciegas, sino que evalúe:

1. si la arquitectura de `Open-Nexus` propuesta es la correcta
2. si el runtime desktop debe seguir apoyandose temporalmente en FastAPI o separarse antes
3. si el pipeline de build elegido es razonable
4. como trasladar correo, CRM y outreach al shell sin arrastrar el layout web

## Secrets

Este paquete no deberia compartirse fuera de un entorno controlado sin revisar secretos.

Especial cuidado con:

- `.env`
- credenciales locales
- keys de API
- usuarios internos del CRM

En el zip preparado para revisión se han excluido secretos runtime sensibles y basura de ejecución cuando no eran necesarios para entender o revisar el código.
