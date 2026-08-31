$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $RepoRoot "build"
$VenvPath = Join-Path $BuildRoot ".venv-open-nexus"
$AppRequirements = Join-Path $RepoRoot "app\requirements\dev.txt"
$DesktopRequirements = Join-Path $RepoRoot "desktop\requirements.txt"
$VerifyScript = Join-Path $RepoRoot "scripts\verify_open_nexus_build.ps1"

Write-Host "Preparando build de Open-Nexus..."

if (!(Test-Path $BuildRoot)) {
    New-Item -ItemType Directory -Path $BuildRoot | Out-Null
}

if (!(Test-Path $VenvPath)) {
    python -m venv $VenvPath
}

$Python = Join-Path $VenvPath "Scripts\python.exe"
$Pip = Join-Path $VenvPath "Scripts\pip.exe"

& $Python -m pip install --upgrade pip
& $Pip install -r $AppRequirements -r $DesktopRequirements
if ($LASTEXITCODE -ne 0) {
    throw "pip install ha fallado con codigo $LASTEXITCODE - build abortada antes de empaquetar dependencias incompletas."
}
& $Python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "pip check ha encontrado conflictos de dependencias - build abortada."
}

Push-Location $RepoRoot
try {
    & $Python -m PyInstaller build\OpenNexus.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller ha fallado con código $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

& $VerifyScript

# El build NO empaqueta .env (no esta en los datas del spec, con razon —
# tiene API keys). AppConfig._resolve_env_files() busca primero en
# %LOCALAPPDATA%\Open-Nexus\.env / _internal\.env — misma ruta fija para
# CUALQUIER copia del exe, este donde este (Desktop, AppData...) — antes
# de caer al .env relativo al repo (que en un build congelado no significa
# nada real). Sin este paso, un exe reconstruido sigue leyendo la ultima
# copia que alguien puso ahi a mano, por muy vieja que sea — paso justo lo
# que le paso a ABRIRNEXUS.exe hoy: .env de hace 3 semanas, con un modelo
# ya borrado del servidor y timeouts demasiado cortos.
$EnvFile = Join-Path $RepoRoot ".env"
if (Test-Path $EnvFile) {
    $LocalAppDataRoot = Join-Path $env:LOCALAPPDATA "Open-Nexus"
    New-Item -ItemType Directory -Path $LocalAppDataRoot -Force | Out-Null
    Copy-Item $EnvFile (Join-Path $LocalAppDataRoot ".env") -Force
    $InternalDir = Join-Path $LocalAppDataRoot "_internal"
    if (Test-Path $InternalDir) {
        Copy-Item $EnvFile (Join-Path $InternalDir ".env") -Force
    }
    Write-Host "Sincronizado .env actual a $LocalAppDataRoot"
} else {
    Write-Warning ".env no encontrado en $RepoRoot — el exe seguira usando la copia que ya tuviera en AppData, si hay alguna."
}

Write-Host ""
Write-Host "Build terminada. Revisa dist\OpenNexus\"
