# IMPLEMENTATION STEP 018

## Paso
Dar a `Nexus` una primera capacidad real de pre diagnóstico sobre Docker cuando el usuario lo pida en el chat.

## Que hago
- Añado un skill nuevo `docker.prediagnostico`.
- Registro una capability local de inspección Docker.
- Extiendo el `DesktopSkillRouter` para detectar peticiones tipo:
  - `tengo una alarma de docker`
  - `revisa el contenedor api-worker`
  - `diagnostica docker`
- Creo un servicio de recogida de evidencias Docker de solo lectura:
  - `docker version`
  - `docker ps -a`
  - `docker inspect`
  - `docker stats --no-stream`
  - `docker logs --tail`
- Conecto el chat de `NexusCoordinator` para que:
  1. detecte el skill Docker
  2. recoja evidencias locales
  3. pase esas evidencias al LLM
  4. devuelva un pre diagnóstico en lenguaje natural

## Que toco
- `app/skills/catalogue/docker_prediagnostico.json`
- `desktop/runtime/capabilities.py`
- `desktop/runtime/skill_router.py`
- `app/nexus/diagnostics/docker_pre_diagnostic.py`
- `app/nexus/orchestration/coordinator.py`
- `app/nexus/api/dependencies/auth.py`
- `tests/unit/test_desktop_runtime.py`
- `tests/unit/test_nexus_coordinator.py`

## Como funciona ahora
- Si el usuario escribe algo como:
  - `tengo una alarma de docker en el contenedor api-worker`
- el chat ya no cae por la ruta general directamente
- primero recoge observaciones reales del entorno Docker local
- luego el LLM construye el pre diagnóstico sobre esas evidencias

## Validacion real
- `POST http://127.0.0.1:5010/api/nexus/chat`
- mensaje:
  - `tengo una alarma de docker en el contenedor api-worker, hazme un pre diagnostico`
- resultado real:
  - `Nexus` detecta que Docker no está levantado en este equipo
  - devuelve un pre diagnóstico explicando que el `Docker Engine` no es accesible

## Tests pasados
- `python -m pytest tests\unit\test_desktop_runtime.py -q`
  - `7 passed`
- `python -m pytest tests\unit\test_nexus_coordinator.py -q`
  - `15 passed`

## Observaciones
- Esta slice no arregla contenedores ni ejecuta acciones destructivas.
- Solo observa y diagnostica.
- El siguiente paso natural es añadir:
  - acciones seguras de remediación en `dry-run`
  - soporte a `docker compose`
  - identificación de tecnología previa a Docker para no asumir contenedores cuando la alarma venga de otro sitio
