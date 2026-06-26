# Audit Release Workflow

## Objetivo

Cuando haya un cambio gordo de producto o una release interna, la preparación para auditoría externa no debe improvisarse.

El flujo estándar de Nexus queda así:

1. detectar que el cambio ya es suficientemente grande
2. avisar explícitamente al usuario con esta frase:

`Angel, esto necesita auditoria`

3. preparar el paquete único de revisión
4. incluir dentro el prompt de revisión como `prompt_revision.md`
5. esperar la respuesta del revisor externo antes de seguir cerrando decisiones estructurales

## Script estándar

Ruta:

- `C:\DEV\Nexus-UI\scripts\prepare_release_audit.ps1`

Uso por defecto:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\prepare_release_audit.ps1
```

Uso con nombre custom:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\prepare_release_audit.ps1 -AuditName 20260529Revision_Audit_IA_GPT
```

## Qué hace

- usa `AUDIT/` como ubicación canónica de auditorías
- crea un staging con nombre de auditoría
- copia código, scripts, docs, tests y base de ingeniería inversa
- excluye secretos sensibles y basura de ejecución
- mete el prompt de revisión como `prompt_revision.md`
- genera un único `.zip`

## Dónde deja el paquete

- `C:\DEV\Nexus-UI\AUDIT\<NOMBRE_AUDITORIA>\`
- `C:\DEV\Nexus-UI\AUDIT\<NOMBRE_AUDITORIA>.zip`
- dentro del ZIP, todo cuelga de la carpeta raíz `Nexus-UI\`

## Qué no mete

- `.env`
- caches de Python
- `.git`
- logs de ejecución
- datos pesados de observabilidad que no aportan a revisión de código

## Cuándo dispararlo

Debe dispararse cuando haya:

- cambio fuerte de arquitectura
- pivot de producto
- integración nueva crítica
- inicio de una línea nueva como desktop, CRM, correo o agentes autónomos
- o justo antes de pedir opinión externa estructural

## Criterio

No usarlo para cada cambio pequeño.
Sí usarlo cuando una revisión externa pueda ahorrar vueltas o errores de dirección.
