# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

repo_root = Path.cwd()
datas = []
required_data_paths = [
    "app/templates",
    "app/static",
    "app/skills/catalogue",
    "app/data/prompts",
    "products/desktop/ui/templates",
    "products/desktop/ui/static",
]

missing_required = [relative for relative in required_data_paths if not (repo_root / relative).exists()]
if missing_required:
    raise SystemExit(
        "OpenNexus.spec no puede continuar. Faltan rutas obligatorias: "
        + ", ".join(missing_required)
    )

for relative in required_data_paths:
    path = repo_root / relative
    datas.append((str(path), relative))

hiddenimports = [
    "apscheduler",
    "apscheduler.schedulers.asyncio",
    "desktop.application",
    "desktop.main",
    "desktop.path_setup",
    "desktop.tray",
    "nexus.bootstrap",
    "nexus.api.dependencies.auth",
    "agents.generation_agent",
    "agents.llm_router",
]

a = Analysis(
    [str(repo_root / "desktop" / "main.py")],
    pathex=[str(repo_root), str(repo_root / "app")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenNexus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(repo_root / "products" / "desktop" / "ui" / "static" / "nexus_anchor.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OpenNexus",
)
