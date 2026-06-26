# Implementation Step 014

## Paso

Conexión del chat de `Nexus v1` al `LLMRouter` real y validación del flujo de API cloud extremo a extremo.

## Que hago

- Conecto `POST /api/nexus/chat` al router LLM real mediante `GenerationAgent`.
- Mantengo el resto del coordinador intacto.
- Verifico que el flujo nuevo ya responde usando OpenRouter.

## Que toco

- `app/nexus/orchestration/coordinator.py`
  - `handle_chat()` deja de devolver un texto fijo
  - ahora usa `GenerationAgent(router=self._llm_router)`

- `app/nexus/api/dependencies/auth.py`
  - el runtime de `Nexus` se construye con `get_router()`

- `tests/unit/test_nexus_coordinator.py`
- `tests/integration/test_nexus_alert_webhook_flow.py`

## Validación real hecha

Se ha probado la app real con `TestClient` sobre `main.app`:

```text
POST /api/nexus/chat
status_code = 200
response = {
  "status": "accepted",
  "response": "Nexus API funcionando.",
  "agent": "GenerationAgent",
  "flow": "chat",
  "audit_id": "..."
}
```

Además, los logs muestran llamada real al modelo:

- nivel `L1`
- modelo `baidu/cobuddy:free`

## Qué demuestra

Ya no solo funciona:

- la key
- el script auxiliar
- el router aislado

También funciona:

- el endpoint real de chat de `Nexus`
- usando el proveedor cloud configurado
- sin modelo local

## Observación operativa

La app sigue arrancando aunque:

- Redis no esté disponible
- MongoDB no esté disponible

Eso para ahora es aceptable porque el flujo `/api/nexus/chat` nuevo no depende de ellos para responder.

## Test pasados

```text
python -m pytest tests\unit\test_nexus_coordinator.py -q
14 passed

python -m pytest tests\integration\test_nexus_alert_webhook_flow.py -q
1 passed
```

## Siguiente paso natural

1. enchufar la UI al endpoint `/api/nexus/chat`
2. renombrar `L1-Groq` en logs a un nombre neutro
3. añadir un segundo proveedor de respaldo
