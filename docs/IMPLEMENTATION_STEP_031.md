# Implementation Step 031

## Paso

Separación del núcleo de ejecución del asistente respecto a las interfaces web y desktop.

## Qué hago

- Creo una capa `AssistantRuntimeCore` para ejecutar peticiones de asistente sin depender de rutas FastAPI ni de la UI desktop.
- Hago que la web use esa capa para `/api/nexus/chat`.
- Hago que `Open-Nexus` use esa misma capa desde el motor desktop.
- Mantengo interfaces separadas: web y desktop no comparten presentación, solo núcleo reutilizable.
- Añado compatibilidad hacia atrás para runtimes y coordinadores fake usados en tests.

## Qué toco

- `C:\DEV\Nexus-UI\app\nexus\application\services\assistant_runtime_core.py`
- `C:\DEV\Nexus-UI\app\nexus\api\dependencies\auth.py`
- `C:\DEV\Nexus-UI\app\nexus\api\routes\chat.py`
- `C:\DEV\Nexus-UI\app\nexus\orchestration\coordinator.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\engine.py`
- `C:\DEV\Nexus-UI\tests\unit\test_open_nexus_engine.py`
- `C:\DEV\Nexus-UI\tests\unit\test_assistant_runtime_core.py`

## Resultado

- Desktop y web pueden ejecutar el asistente sobre una base común sin compartir UI.
- El shell desktop ya no baja tan directamente al coordinador web.
- La web sigue funcionando sin cambiar su interfaz.

## Tests

- `python -m pytest tests\unit\test_assistant_runtime_core.py tests\unit\test_open_nexus_engine.py tests\e2e\test_nexus_v1_api.py -q`
- Resultado: `12 passed`
