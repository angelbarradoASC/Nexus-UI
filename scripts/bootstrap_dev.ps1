$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3.11 -c "import sys; print(sys.version)" | Out-Null
            return @("py", "-3.11")
        } catch {
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "No se ha encontrado Python. Instala Python 3.11 o aseguralo en PATH."
}

function Invoke-Python {
    param(
        [string[]]$PythonCommand,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    $Executable = $PythonCommand[0]
    $PrefixArgs = @()
    if ($PythonCommand.Length -gt 1) {
        $PrefixArgs = $PythonCommand[1..($PythonCommand.Length - 1)]
    }

    & $Executable @PrefixArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo ejecutando Python: $($Arguments -join ' ')"
    }
}

$PythonCommand = Resolve-PythonCommand
$VenvPath = Join-Path $RepoRoot ".venv"

if (-not (Test-Path $VenvPath)) {
    Write-Host "Creando .venv con Python canonico..."
    Invoke-Python -PythonCommand $PythonCommand -Arguments @("-m", "venv", ".venv")
} else {
    Write-Host "Reutilizando entorno virtual existente en .venv"
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "No se ha encontrado el Python del entorno virtual en $VenvPython"
}

Write-Host "Actualizando pip..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo actualizar pip."
}

Write-Host "Instalando dependencias de desarrollo..."
& $VenvPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron instalar las dependencias de desarrollo."
}

Write-Host "Comprobando imports minimos..."
& $VenvPython -c "import fastapi, pytest, bson, paramiko; print('imports-ok')"
if ($LASTEXITCODE -ne 0) {
    throw "Fallaron los imports minimos (fastapi, pytest, bson, paramiko)."
}

$ObscuraVersion = "v0.2.0"
$ObscuraDir = Join-Path $RepoRoot "vendor\obscura"
$ObscuraExe = Join-Path $ObscuraDir "obscura.exe"
if (-not (Test-Path $ObscuraExe)) {
    Write-Host "Descargando Obscura $ObscuraVersion (renderizado JS local para prospeccion)..."
    New-Item -ItemType Directory -Force -Path $ObscuraDir | Out-Null
    $ObscuraZip = Join-Path $env:TEMP "obscura-x86_64-windows-stealth.zip"
    $ObscuraUrl = "https://github.com/h4ckf0r0day/obscura/releases/download/$ObscuraVersion/obscura-x86_64-windows-stealth.zip"
    Invoke-WebRequest -Uri $ObscuraUrl -OutFile $ObscuraZip
    Expand-Archive -Path $ObscuraZip -DestinationPath $ObscuraDir -Force
    Remove-Item $ObscuraZip
} else {
    Write-Host "Obscura ya presente en $ObscuraExe"
}

Write-Host ""
Write-Host "Bootstrap completado."
Write-Host "Python canonico: $VenvPython"
