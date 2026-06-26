# Open-Nexus Build And Install

## Objetivo

Open-Nexus pasa a tratarse como producto de escritorio instalable, no como simple superficie web.

La base actual incluye:

- shell local de consola
- runtime Nexus reutilizado
- spec de PyInstaller
- script de build
- script de instalacion Windows

## Entry point principal

El entry point nuevo es:

- `C:\DEV\Nexus-UI\desktop\open_nexus_main.py`

Para probarlo en desarrollo:

```powershell
python -m desktop.open_nexus_main
```

## Build

Script:

- `C:\DEV\Nexus-UI\scripts\build_open_nexus.ps1`

Uso:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\build_open_nexus.ps1
```

Que hace:

- crea un venv de build en `build\.venv-open-nexus`
- instala dependencias necesarias para empaquetado
- ejecuta PyInstaller con:
  - `C:\DEV\Nexus-UI\build\OpenNexus.spec`

Salida esperada:

- `C:\DEV\Nexus-UI\dist\OpenNexus\`

## Instalacion Windows

Script:

- `C:\DEV\Nexus-UI\scripts\install_open_nexus_windows.ps1`

Uso:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DEV\Nexus-UI\scripts\install_open_nexus_windows.ps1
```

Que hace:

- lanza el build
- copia artefactos a `%LOCALAPPDATA%\Open-Nexus`
- crea acceso directo en escritorio

## Estado actual

Esto ya prepara el pipeline de producto, pero no es todavia el instalador final de distribucion.

Lo que ya existe:

- pipeline reproducible de build
- layout de empaquetado
- runtime local shell-first

Lo que falta:

- cerrar todas las dependencias exactas de distribucion
- probar build real de PyInstaller end-to-end
- firmar artefactos si toca
- preparar un instalador mas fino si se quiere MSI, Inno Setup o similar

## Decision de producto

El shell `Open-Nexus` es la pieza principal.

La ruta `/open-nexus` en el runtime webview solo existe como puente temporal para no romper el desktop actual mientras se sustituye por el producto instalable final.
