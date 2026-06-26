$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $RepoRoot "dist\OpenNexus"
$RequiredPathGroups = @(
    @("OpenNexus.exe"),
    @("app\templates", "_internal\app\templates"),
    @("app\static", "_internal\app\static"),
    @("app\skills\catalogue", "_internal\app\skills\catalogue"),
    @("app\data\prompts", "_internal\app\data\prompts"),
    @("products\desktop\ui\templates", "_internal\products\desktop\ui\templates"),
    @("products\desktop\ui\static", "_internal\products\desktop\ui\static")
)

if (!(Test-Path $DistRoot)) {
    throw "No existe dist\OpenNexus. El build no ha generado artefactos."
}

$Missing = @()
foreach ($CandidateGroup in $RequiredPathGroups) {
    $Resolved = $false
    foreach ($RelativePath in $CandidateGroup) {
        $Target = Join-Path $DistRoot $RelativePath
        if (Test-Path $Target) {
            $Resolved = $true
            break
        }
    }
    if (-not $Resolved) {
        $Missing += ($CandidateGroup -join " | ")
    }
}

if ($Missing.Count -gt 0) {
    throw "El build de Open-Nexus está incompleto. Faltan: $($Missing -join ', ')"
}

Write-Host "Verificación de build OK."
