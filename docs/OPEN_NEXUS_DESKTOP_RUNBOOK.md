# Open-Nexus Desktop Runbook

## Objetivo

Este documento deja fijado como se arranca la aplicacion desktop real de `Nexus-UI`.

La aplicacion que debe considerarse canonicamente operativa es la **desktop**:

- backend local: `products/desktop/backend/app.py`
- cliente nativo: `desktop/main.py`
- ventana desktop: `pywebview` sobre `WebView2`

## Punto de entrada canonico

El punto de entrada recomendado para abrir la app es:

- `scripts/start_open_nexus_desktop.ps1`

Comando:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\start_open_nexus_desktop.ps1
```

Alias compatible:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\run_open_nexus_dev.ps1
```

## Que hace el script de arranque

`start_open_nexus_desktop.ps1` esta pensado para evitar arranques corruptos o ambiguos.

Hace esto, en este orden:

1. Comprueba si ya hay una instancia sana respondiendo en `http://127.0.0.1:11430/health`.
2. Si ya esta sana, no relanza nada y sale limpio.
3. Si el puerto `11430` esta ocupado por un proceso conocido de preview o desktop antiguo, lo cierra.
4. Si el puerto `11430` esta ocupado por un proceso ajeno, falla con mensaje claro en vez de matar algo que no debe.
5. Mata restos conocidos que suelen dejar el desktop en mal estado:
   - `run_preview.py`
   - `python -m desktop.main`
   - `python -m desktop.open_nexus_main`
   - `OpenNexus.exe`
6. Arranca `python -m desktop.main`.
   - Si existe `pythonw.exe`, lo usa para que no aparezca una consola negra adicional.
7. Espera hasta que el backend desktop responda en `/health`.
8. Intenta confirmar que aparece la ventana `Open-Nexus`.

## Reinicio forzado

Si hace falta rehacer el arranque desde cero:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\start_open_nexus_desktop.ps1 -ForceRestart
```

Esto fuerza la limpieza de restos y vuelve a levantar la app.

## Señales de arranque sano

El desktop se considera bien levantado cuando se cumplen estas dos cosas:

1. Existe una ventana llamada `Open-Nexus`.
2. `GET http://127.0.0.1:11430/health` devuelve algo de esta forma:

```json
{
  "status": "ok",
  "context": "desktop_app",
  "backend": "desktop"
}
```

## Logs utiles

Logs de arranque:

- `logs/desktop-launch.out.log`
- `logs/desktop-launch.err.log`

Log general del sistema:

- `logs/nexus.log`

## Accesos directos

Los accesos directos de Windows deben abrir el desktop real, no el shell de consola ni un preview viejo.

En esta base de codigo:

- `scripts/run_open_nexus_dev.ps1` delega al lanzador canonico
- `scripts/install_open_nexus_windows.ps1` crea accesos directos en los escritorios detectados de Windows

## Nota de plataforma

El runtime desktop actual esta pensado para Windows porque depende de:

- PowerShell
- `pywebview`
- Microsoft `WebView2`
- system tray y procesos locales de Windows

Eso no impide que este documento se pueda leer desde cualquier plataforma, pero el arranque soportado hoy para la app desktop real es **Windows**.
