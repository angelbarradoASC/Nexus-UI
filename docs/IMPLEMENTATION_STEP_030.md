# Implementation Step 030

## Paso

Primera pasada de endurecimiento `P0` para `Open-Nexus`.

## Qué hago

- Arreglo el arranque desktop para que prepare rutas de import de forma explícita.
- Muevo la configuración de entorno del entrypoint para que ocurra antes de importar el shell pesado.
- Reutilizo el bootstrap de paths también en el servidor local embebido.
- Corrijo el `OpenNexus.spec` para empaquetar `app/data/prompts`.
- Hago que el build deje de instalar dependencias a mano y use requirements versionados.
- Añado verificación post-build.
- Dejo utilidades mínimas de desarrollo para arrancar `Open-Nexus` sin magia.

## Qué toco

- `C:\DEV\Nexus-UI\desktop\path_setup.py`
- `C:\DEV\Nexus-UI\desktop\open_nexus_main.py`
- `C:\DEV\Nexus-UI\desktop\opennexus\engine.py`
- `C:\DEV\Nexus-UI\desktop\services\local_server.py`
- `C:\DEV\Nexus-UI\desktop\requirements.txt`
- `C:\DEV\Nexus-UI\build\OpenNexus.spec`
- `C:\DEV\Nexus-UI\scripts\build_open_nexus.ps1`
- `C:\DEV\Nexus-UI\scripts\verify_open_nexus_build.ps1`
- `C:\DEV\Nexus-UI\scripts\run_open_nexus_dev.ps1`
- `C:\DEV\Nexus-UI\.env.desktop.example`
- `C:\DEV\Nexus-UI\tests\unit\test_open_nexus_entrypoint.py`

## Validación que espero

- `python -m desktop.open_nexus_main` importa sin depender del orden casual de imports.
- `desktop.open_nexus_main` ya no carga el shell antes de fijar el entorno.
- el build falla si faltan assets obligatorios.
- el build verifica que el artefacto contiene prompts, static, templates y skills.

## Siguiente bloque

- validar arranque real desde repo root
- revisar si sigue habiendo imports frágiles fuera del bootstrap nuevo
- empezar la capa de runtime compartido sin arrastrar más web al shell
