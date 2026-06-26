# Implementation Step 008

## Paso

Base del runtime de escritorio para `Nexus` como asistente general local, no solo como ventana que embebe la web.

## Que hago

- Creo el primer `desktop runtime` compartido entre la app de escritorio y el backend embebido.
- Meto un registro de capacidades locales con niveles de permiso.
- Expongo ese runtime por API para poder inspeccionarlo desde la propia aplicacion.
- Corrijo el tray para que use el token interno del desktop al lanzar acciones locales.
- Mantengo la base compatible con el runtime actual y con los smoke tests existentes.

## Que toco

### Nuevos modulos

- `desktop/runtime/__init__.py`
- `desktop/runtime/capabilities.py`
- `desktop/runtime/assistant_runtime.py`
- `desktop/runtime/bootstrap.py`

### Modulos actualizados

- `desktop/application.py`
  - inicializa el runtime local del asistente
  - lo registra para que el backend embebido pueda verlo
  - pasa el token interno al tray

- `desktop/tray.py`
  - manda `Authorization: Bearer <desktop_internal_token>` en quick actions internas

- `app/main.py`
  - añade `GET /api/desktop/runtime`
  - devuelve descripcion del runtime desktop cuando el contexto es `desktop_app`

### Tests

- `tests/unit/test_desktop_runtime.py`
  - valida el runtime y el filtrado por permisos

- `tests/smoke/test_smoke_desktop.py`
  - valida el endpoint nuevo `/api/desktop/runtime`

## Referencia tomada

Se ha tomado como referencia conceptual `OpenCode`, verificando en fecha `2026-05-14` que su enfoque publico sigue apoyandose en:

- motor comun entre terminal, desktop e IDE
- gestion de sesiones
- herramientas/capacidades compartidas
- permisos alrededor del uso de herramientas

Fuentes consultadas:

- [OpenCode](https://opencode.ai/)
- [Repositorio archivado original de OpenCode en GitHub](https://github.com/opencode-ai/opencode/)

La inferencia aplicada para `Nexus Desktop` es:

- no copiar su interfaz
- si copiar la separacion entre superficie y runtime
- si tratar el escritorio como motor local del asistente

## Test pasados

```text
python -m pytest tests\unit\test_desktop_runtime.py -q
4 passed

python -m pytest tests\smoke\test_smoke_desktop.py -q
9 passed
```

## Resultado

`Nexus Desktop` ya no depende solo de:

- ventana
- tray
- backend local
- agente de monitorizacion

Ahora tiene una base explicita para crecer como asistente general local:

- capacidades
- permisos
- sesion runtime
- exposicion interna del estado del motor desktop

## Siguiente paso natural

1. crear un `skill router` local para desktop
2. definir `intent -> capability set` en vez de `intent -> accion fija`
3. colgar la futura UI desktop de este runtime y no de endpoints sueltos
