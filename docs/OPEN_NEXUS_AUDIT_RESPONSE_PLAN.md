# Open-Nexus Audit Response Plan

## Contexto

La auditoría externa de `20260528Revision_Audit_IA_GPT.zip` valida la dirección general del producto, pero deja claro que `Open-Nexus` todavía está en fase de transición y no debe seguir creciendo por features antes de endurecer su base desktop.

Este documento traduce esa revisión en un plan de trabajo priorizado.

## Resumen ejecutivo

No hay que rehacer el producto.
Sí hay que cambiar el orden de ejecución.

La prioridad no es meter más CRM, más correo ni más pantallas.
La prioridad es conseguir que `Open-Nexus`:

- arranque limpio en desarrollo
- empaquete limpio
- instale limpio
- tenga una interfaz runtime compartida
- y empiece a comportarse como producto desktop real

## Decisión de dirección

### Lo que mantenemos

- Pivot de web-first a desktop-first
- `Open-Nexus` como shell principal
- Referencia de Open Interpreter como modelo de producto
- Capability registry
- Runtime local y scripts de build/install

### Lo que congelamos temporalmente

- nuevas pantallas web
- más features en `/nexus-v1`
- nuevas integraciones de negocio sobre la web
- automatismos complejos de agentes sobre la base actual

### Lo que corregimos primero

- arranque del entrypoint desktop
- acoplamientos de import/config
- build PyInstaller
- dependencias de build
- persistencia local mínima
- permisos y estructura de runtime

## Prioridades

## P0. Arranque limpio de Open-Nexus

### Objetivo

Poder ejecutar esto desde la raíz del repo sin magia:

```powershell
python -m desktop.open_nexus_main
```

### Problemas a corregir

- `desktop/opennexus/engine.py` depende de `from config import cfg`
- la configuración real vive en `app/config.py`
- el runtime desktop depende demasiado pronto de la estructura web

### Acciones

1. Mover o exponer la configuración compartida mediante imports absolutos estables.
2. Evitar dependencias implícitas de `PYTHONPATH=app`.
3. Crear un bootstrap de desarrollo claro para desktop.
4. Añadir un smoke test que valide import y arranque mínimo.

### Criterio de cierre

- `python -m desktop.open_nexus_main` arranca desde repo root
- si falta configuración, el error es explícito y entendible
- tests del entrypoint y runtime pasan sin hacks de path

## P0. Build reproducible y verificable

### Objetivo

Que el build deje de depender de suerte y pip manual.

### Problemas a corregir

- `OpenNexus.spec` apunta mal a `data/prompts`
- el script de build instala paquetes a mano
- no hay verificación post-build

### Acciones

1. Corregir rutas de assets en `build/OpenNexus.spec`.
2. Crear requirements de build claros y versionados.
3. Cambiar el script de build para instalar desde requirements.
4. Añadir `pip check`.
5. Añadir script `verify_open_nexus_build.ps1`.

### Criterio de cierre

- el build incluye prompts, static, templates y catálogo de skills
- el binario se genera de forma repetible
- existe una verificación automática mínima post-build

## P1. Separación real entre web y desktop

### Objetivo

Que `Open-Nexus` y la web sean productos distintos en interfaz y experiencia, aunque puedan compartir núcleo de dominio o servicios internos.

### Problemas a corregir

- el shell desktop detecta intención, pero sigue bajando al coordinador web
- desktop y web pueden divergir en routing
- la web sigue pesando demasiado en decisiones de arquitectura

### Acciones

1. Separar explícitamente capa de interfaz, capa de aplicación y capa de dominio.
2. Mantener independientes las interfaces de web y desktop.
3. Compartir solo lógica de dominio o servicios reutilizables cuando tenga sentido.
4. Reducir dependencias directas del shell respecto a schemas o wiring web.
5. Tratar `/open-nexus` como puente temporal y no como producto final.

### Criterio de cierre

- web y desktop tienen interfaces independientes
- el shell no depende directamente de la estructura FastAPI
- lo compartido vive en núcleo/aplicación, no en la presentación

## P1. Persistencia local mínima

### Objetivo

Dar al shell memoria local y estructura de trabajo propia.

### Acciones

1. Crear estructura local en `%LOCALAPPDATA%/Open-Nexus/`.
2. Guardar historial local.
3. Guardar perfiles/configuración básica.
4. Añadir comandos de shell para inspección de config y providers.

### Criterio de cierre

- el shell conserva historial entre sesiones
- existe un sitio claro para logs, config e historial

## P1. Permisos antes que acciones reales

### Objetivo

No abrir la puerta a ejecución local fuerte sin control.

### Acciones

1. Hacer que cada skill declare capacidades y nivel de permiso.
2. Pedir confirmación explícita en acciones `OPERATE` y `ADMIN`.
3. Auditar cada ejecución local.
4. Mantener bloqueados los comandos locales libres hasta que la capa esté madura.

### Criterio de cierre

- no hay ejecuciones sensibles sin confirmación
- cada acción queda registrada

## P2. Instalador de producto, no solo bootstrap de dev

### Objetivo

Tener una instalación seria de Windows.

### Acciones

1. Separar claramente build, install y verify.
2. Crear estructura de datos local en instalación.
3. Comprobar prerequisitos.
4. Tratar el script actual como `developer installer` hasta endurecerlo.

### Criterio de cierre

- instalar deja la app lista para arrancar
- si algo falta, el error es concreto y guiado

## Qué no vamos a tocar ahora

- nuevas vistas web funcionales
- más expansión de `nexus-v1`
- más automatismos de outreach en la web
- nuevas integraciones profundas hasta que el desktop sea estable

## Roadmap corto propuesto

### Sprint 1

- P0 arranque limpio
- P0 build reproducible

### Sprint 2

- P1 runtime compartido web/desktop
- P1 persistencia local

### Sprint 3

- P1 permisos
- P2 instalador más serio

### Sprint 4

- migración real de correo/CRM/outreach al shell desktop

## Criterio de disciplina

Hasta cerrar P0 y P1, no deberíamos volver a meter funcionalidades nuevas grandes en la superficie web.

La regla buena es:

primero columna vertebral,
después flujos,
después músculo.
