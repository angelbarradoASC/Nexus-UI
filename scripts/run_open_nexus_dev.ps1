$ErrorActionPreference = "Stop"

$StartScript = Join-Path $PSScriptRoot "start_open_nexus_desktop.ps1"

& powershell -ExecutionPolicy Bypass -File $StartScript @args
