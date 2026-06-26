# Open-Nexus Migration Plan

## Principio

No vamos a rehacer el producto entero de golpe.
Tampoco vamos a intentar portar cada tarjeta de la web al escritorio una por una.
Y tampoco vamos a compartir interfaz entre web y desktop.

Vamos a migrar por capas:

- motor
- shell
- workflows
- empaquetado

La regla buena es esta:

- web y desktop son superficies distintas
- lo compartido debe vivir en dominio, servicios o adaptadores
- la experiencia de uso del escritorio no debe depender visualmente de la web

## Fase 0. Base ya hecha

Estado actual:

- runtime desktop existente
- routing local de skills
- shell inicial `Open-Nexus`
- build spec
- script de build
- script de instalación
- ruta puente `/open-nexus`
- documentación de ingeniería inversa

Objetivo de esta fase:

- tener una columna vertebral ejecutable

## Fase 1. Shell utilizable

Meta:

- que `Open-Nexus` sirva para trabajar aunque el UI rico todavía no esté completo

Trabajo:

- mejorar el shell interactivo
- añadir comandos internos estables
- mostrar mejor el routing
- guardar historial local de sesión
- mostrar estado de runtime y capacidades sin depender de la web

Resultado esperado:

- una experiencia tipo operador local usable

## Fase 2. Inbox y ventas

Meta:

- trasladar el trabajo comercial real al escritorio

Trabajo:

- integrar correo prioritario en el shell/panel local
- convertir respuestas en acciones
- integrar campañas de outreach como workflow
- sincronizar CRM dentro del mismo flujo
- hacerlo con experiencia propia de escritorio, no replicando pantallas web

Resultado esperado:

- poder revisar, preparar y seguir campañas desde Open-Nexus

## Fase 3. Operaciones e incidencias

Meta:

- hacer que Open-Nexus también sea puesto de mando técnico

Trabajo:

- estado de recolectores en runtime local
- timeline de actividad
- acceso a incidentes
- diagnóstico guiado por skills
- visibilidad de auditoría

Resultado esperado:

- que un operador pueda usar Open-Nexus como consola de trabajo

## Fase 4. Configuración avanzada

Meta:

- mover las herramientas de tuning y configuración al producto desktop

Trabajo:

- editor de prompts dentro de Open-Nexus
- perfiles de proveedores LLM
- límites, permisos y políticas
- configuración local persistida

Resultado esperado:

- reducir dependencia de editar `.env` y tocar código

## Fase 5. Distribución seria

Meta:

- cerrar el producto instalable de verdad

Trabajo:

- build reproducible
- validación de artefactos
- instalador más fino si hace falta
- runtime dependencies completas
- smoke tests de instalación

Resultado esperado:

- `.exe` + instalación repetible

## Orden de migración funcional

### Primero

- chat/routing
- runtime
- skills
- historial local

### Después

- correo
- outreach
- CRM

### Luego

- observabilidad
- actividad
- incidentes

### Al final

- prompts
- configuración avanzada
- reemplazo total del puente web

## Qué no hacer

- seguir engordando la web como si fuera el producto final
- meter nuevas tarjetas grandes porque “ya estaban”
- duplicar lógica entre web y escritorio
- compartir presentación entre web y escritorio
- construir una interfaz nativa rica antes de cerrar el runtime y el shell

## Criterio de éxito

Open-Nexus estará en buena dirección cuando:

- el usuario pueda arrancarlo como ejecutable
- pueda hablar con él sin abrir navegador
- pueda operar correo/CRM desde ahí
- y la web haya pasado a ser secundaria
