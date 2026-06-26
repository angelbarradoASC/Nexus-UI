# Implementation Step 023

## Paso

Integrar `Nexus Operator` en el sistema de arranque desktop para que:

- el servidor local embebido siga siendo la base del shell
- la ventana principal abra directamente el panel `/nexus-v1`
- el tray siempre vuelva al panel operador
- Windows arranque Nexus automaticamente al iniciar sesion

## Que hice

1. Añadi configuracion de arranque desktop:
   - `startup_route`
   - `startup_url`
   - `open_operator_on_start`

2. Cambie la ventana principal de desktop para que abra:
   - `http://127.0.0.1:<puerto>/nexus-v1`

3. Actualice el tray para que:
   - abra `Nexus Operator`
   - tenga accesos a outreach y panel operador
   - deje de mandar al usuario a un JSON de metricas

4. Hice mas robusto el `LocalServer`:
   - añade `repo_root` al `sys.path`
   - reduce friccion de imports entre `app/` y `desktop/`

5. Añadi scripts de autoarranque de Windows:
   - `scripts/install_windows_startup.ps1`
   - `scripts/remove_windows_startup.ps1`

6. Instale el shortcut de startup del usuario actual.

## Que toque

- `desktop/config.py`
- `desktop/application.py`
- `desktop/tray.py`
- `desktop/services/local_server.py`
- `tests/unit/test_desktop_runtime.py`
- `tests/unit/test_desktop_application.py`
- `scripts/install_windows_startup.ps1`
- `scripts/remove_windows_startup.ps1`

## Tests

- `python -m pytest tests\unit\test_desktop_runtime.py tests\unit\test_desktop_application.py tests\smoke\test_smoke_desktop.py -q`
  - `21 passed`

- `python -m pytest tests\unit\test_config.py tests\e2e\test_nexus_v1_api.py -q`
  - `30 passed`

## Validacion

Se valido el shortcut de arranque instalado en:

- `C:\Users\angel\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Nexus Operator.lnk`

Con:

- `TargetPath = pythonw.exe`
- `Arguments = -m desktop.main`
- `WorkingDirectory = C:\DEV\Nexus-UI`

## Observaciones

Esto deja el desktop mucho mas alineado con la idea base tipo `Open Interpreter`:

- shell local
- runtime persistente
- superficie operativa principal
- agentes por debajo

La parte de login y endurecimiento de sesion desktop se puede seguir refinando despues, pero el puesto de mando ya queda como entrada natural del sistema.
