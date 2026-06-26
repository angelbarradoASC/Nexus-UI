# Implementation Step 029

## Paso

Mover el flujo de empaquetado de revisiones técnicas a `AUDIT/` como ubicación canónica.

## Qué hago

- Cambio el script de preparación de auditorías para que escriba staging y ZIP bajo `AUDIT/`.
- Mantengo el nombre de auditoría como unidad de trabajo (`YYYYMMDDRevision_Audit_IA_GPT`).
- Evito limpiar carpetas históricas de `AUDIT/` para no cargarnos revisiones anteriores.
- Documento la ubicación correcta del paquete de auditoría.

## Qué toco

- `C:\DEV\Nexus-UI\scripts\prepare_release_audit.ps1`
- `C:\DEV\Nexus-UI\docs\AUDIT_RELEASE_WORKFLOW.md`

## Resultado esperado

- Cada auditoría nueva se prepara en:
  - `C:\DEV\Nexus-UI\AUDIT\<NOMBRE>\`
  - `C:\DEV\Nexus-UI\AUDIT\<NOMBRE>.zip`
- El usuario ya no tiene que buscar nada en `exports/`.

## Tests / validación

- Ejecutar el script con el nombre `20260528Revision_Audit_IA_GPT`
- Verificar que el ZIP y el staging quedan en `AUDIT/`
- Verificar que el ZIP contiene carpeta raíz `Nexus-UI\`
