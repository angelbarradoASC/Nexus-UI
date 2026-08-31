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

Write-Host ""
Write-Host "Build terminada. Revisa dist\OpenNexus\"
