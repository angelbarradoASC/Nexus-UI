$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PytestLog = Join-Path $RepoRoot "runtime\logs\pytest-contract.log"
if (-not (Test-Path $VenvPython)) {
    throw "No existe .venv. Ejecuta antes .\scripts\bootstrap_dev.ps1"
}

Write-Host "Verificando contrato UI..."
& $VenvPython "scripts/audit/check_ui_contract.py"
if ($LASTEXITCODE -ne 0) {
    throw "Fallo el contrato de UI."
}

Write-Host "Ejecutando pytest -q..."
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PytestLog) | Out-Null
if (Test-Path $PytestLog) {
    Remove-Item $PytestLog -Force
}

& $VenvPython -m pytest -q *> $PytestLog
$PytestExitCode = $LASTEXITCODE
Get-Content $PytestLog
if ($PytestExitCode -ne 0) {
    throw "Fallo pytest -q."
}

Write-Host "Contrato y tests completados."
