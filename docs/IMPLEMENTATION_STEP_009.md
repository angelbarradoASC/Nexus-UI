# Implementation Step 009

## Paso

Primer router local de skills para `Nexus Desktop`, conectado al runtime del asistente.

## Que hago

- Aprovecho el catálogo real de skills compartido por la aplicación.
- Creo una vista local del catálogo para desktop, sin depender de imports frágiles del backend web.
- Monto un `skill router` local que:
  - clasifica peticiones comunes
  - extrae entidades básicas
  - propone el `skill_id` más probable
  - enlaza el skill con capacidades desktop y nivel de permiso
- Expongo esa resolución por API local para que luego la UI desktop pueda consumirla.
- Actualizo la sesión runtime del escritorio cada vez que se resuelve una petición.

## Que toco

### Nuevos módulos

- `desktop/runtime/skills.py`
  - carga el catálogo desde `app/skills/catalogue/*.json`
  - define `DesktopSkill` y `DesktopSkillCatalogue`

- `desktop/runtime/skill_router.py`
  - define `DesktopSkillRouter`
  - resuelve peticiones hacia:
    - `fichaje.entrada`
    - `fichaje.salida`
    - `jira.crear_ticket`
    - `jira.consultar_ticket`
    - `ssh.diagnostico`
    - `web.busqueda`
    - `general.respuesta`

### Módulos actualizados

- `desktop/runtime/assistant_runtime.py`
  - añade catálogo de skills
  - añade router local
  - expone `resolve_user_input()`
  - incluye resumen de skills en `describe()`

- `app/main.py`
  - añade `POST /api/desktop/resolve`

### Tests

- `tests/unit/test_desktop_runtime.py`
  - prueba resolución de diagnóstico
  - prueba actualización de sesión runtime

- `tests/smoke/test_smoke_desktop.py`
  - prueba del endpoint `POST /api/desktop/resolve`

## Resultado

`Nexus Desktop` ya no es solo:

- servidor embebido
- tray
- monitor local

Ahora también tiene una primera capa de comportamiento como asistente general:

- entiende mejor qué tipo de ayuda se le pide
- propone un skill operativo
- deja claro qué capacidades locales necesitaría
- marca si la acción debería pasar a modo guiado o requerir confirmación

## Test pasados

```text
python -m pytest tests\unit\test_desktop_runtime.py -q
6 passed

python -m pytest tests\smoke\test_smoke_desktop.py -q
10 passed
```

## Siguiente paso natural

1. convertir la resolución en `plan de ejecución` en vez de solo `skill candidato`
2. conectar `ssh.diagnostico` con un capability bridge real
3. empezar el bucle `investigar -> observar -> reinterpretar -> siguiente acción`
