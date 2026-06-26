# Implementation Step 032

## Paso

Persistencia local mínima para `Open-Nexus`.

## Qué hago

- Defino rutas locales de escritorio bajo `%LOCALAPPDATA%/Open-Nexus`.
- Añado directorios para `config`, `logs` e `history`.
- Persisto historial del shell en JSONL.
- Hago que el motor recupere historial al arrancar una nueva instancia.
- Hago que la aplicación desktop cree el layout local aunque no arranque el shell.
- Añado comando `/paths` al shell para inspeccionar las rutas locales.

## Qué toco

- `C:\DEV\Nexus-UI\desktop\config.py`
- `C:\DEV\Nexus-UI\desktop\storage\local_state.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\models.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\engine.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\shell.py`
- `C:\DEV\Nexus-UI\desktop\application.py`
- `C:\DEV\Nexus-UI\tests\unit\test_desktop_runtime.py`
- `C:\DEV\Nexus-UI\tests\unit\test_open_nexus_engine.py`

## Resultado

- `Open-Nexus` ya tiene memoria local mínima.
- El historial del shell sobrevive entre instancias.
- La app desktop tiene una estructura local estable donde crecer.

## Tests

- `python -m pytest tests\unit\test_desktop_runtime.py tests\unit\test_open_nexus_engine.py tests\unit\test_desktop_application.py -q`
- Resultado: `15 passed`
