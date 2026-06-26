param(
    [string]$AuditName = "",
    [string]$PromptSource = "C:\DEV\Nexus-UI\docs\AI_REVIEW_PROMPT_20260528.md"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$AuditRoot = Join-Path $RepoRoot "AUDIT"

if ([string]::IsNullOrWhiteSpace($AuditName)) {
    $AuditName = (Get-Date -Format "yyyyMMdd") + "Revision_Audit_IA_GPT"
}

$StageDir = Join-Path $AuditRoot $AuditName
$ZipPath = Join-Path $AuditRoot ($AuditName + ".zip")
$PackageRoot = Join-Path $StageDir "Nexus-UI"

Write-Host "Preparando auditoria de release: $AuditName"

if (!(Test-Path $AuditRoot)) {
    New-Item -ItemType Directory -Path $AuditRoot | Out-Null
}

if (Test-Path $StageDir) {
    Remove-Item $StageDir -Recurse -Force
}

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

New-Item -ItemType Directory -Path $StageDir | Out-Null
New-Item -ItemType Directory -Path $PackageRoot | Out-Null

$IncludeItems = @(
    "app",
    "desktop",
    "docs",
    "scripts",
    "tests",
    "build",
    "vendor",
    "worker",
    "examples",
    "monitoring",
    "static",
    "templates",
    ".env.api-only.example",
    ".env.nvidia.example",
    ".gitignore",
    "docker-compose.yml",
    "Makefile",
    "pytest.ini",
    "test_intention.py"
)

foreach ($Item in $IncludeItems) {
    $Source = Join-Path $RepoRoot $Item
    if (Test-Path $Source) {
        $Destination = Join-Path $PackageRoot $Item
        $Parent = Split-Path $Destination -Parent
        if (!(Test-Path $Parent)) {
            New-Item -ItemType Directory -Path $Parent -Force | Out-Null
        }
        Copy-Item $Source $Destination -Recurse -Force
    }
}

Get-ChildItem $PackageRoot -Recurse -Force -Directory | Where-Object {
    $_.Name -in @(".git", ".pytest_cache", "__pycache__", "logs", "mongodb", "redis", "tempo-data") -or
    $_.FullName -like "*\grafana\data*"
} | Sort-Object FullName -Descending | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Get-ChildItem $PackageRoot -Recurse -Force -File -Include *.pyc | Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path $PromptSource) {
    Copy-Item $PromptSource (Join-Path $PackageRoot "prompt_revision.md") -Force
}

Compress-Archive -Path $PackageRoot -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "Auditoria preparada:"
Write-Host "ZIP:  $ZipPath"
Write-Host "DIR:  $StageDir"
