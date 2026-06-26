$ErrorActionPreference = "Stop"

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = Join-Path $env:LOCALAPPDATA "Open-Nexus"
$InstalledExe = Join-Path $InstallRoot "OpenNexus.exe"
$InstalledIcon = Join-Path $InstallRoot "nexus_anchor.ico"
$PayloadZip = Join-Path $SourceRoot "payload.zip"
$EnvPath = Join-Path $InstallRoot ".env"
$LegacyLauncherPath = Join-Path $InstallRoot "OpenNexusLauncher.vbs"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Open-Nexus"
$StartupFolder = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$StartupShortcut = Join-Path $StartupFolder "Nexus Operator.lnk"
$ExcludedNames = @(
    "install_open_nexus_client.ps1",
    "install_open_nexus_client.cmd",
    "OpenNexusInstaller.sed",
    "payload.zip"
)

function New-RandomSecret {
    param([int]$Bytes = 48)

    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if (!(Test-Path $PayloadZip)) {
    throw "No se ha encontrado payload.zip en $SourceRoot"
}

Get-Process -Name "OpenNexus" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (!(Test-Path $InstallRoot)) {
    New-Item -ItemType Directory -Path $InstallRoot | Out-Null
}

$ExtractRoot = Join-Path $env:TEMP ("OpenNexusInstall-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $ExtractRoot | Out-Null
try {
    Expand-Archive -Path $PayloadZip -DestinationPath $ExtractRoot -Force
    Get-ChildItem -Path $ExtractRoot -Force | ForEach-Object {
        Copy-Item $_.FullName $InstallRoot -Recurse -Force
    }
}
finally {
    if (Test-Path $ExtractRoot) {
        Remove-Item $ExtractRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (!(Test-Path $InstalledExe)) {
    throw "La instalacion no ha dejado $InstalledExe"
}

$SourceIcon = Join-Path $InstallRoot "products\desktop\ui\static\nexus_anchor.ico"
if (Test-Path $SourceIcon) {
    Copy-Item $SourceIcon $InstalledIcon -Force
}

if (Test-Path $LegacyLauncherPath) {
    Remove-Item $LegacyLauncherPath -Force -ErrorAction SilentlyContinue
}

$secretKey = New-RandomSecret
$credentialStoreKey = New-RandomSecret
$envContent = @"
NEXUS_CONTEXT=desktop_app
APP_PORT=11430
DEBUG=false
SECRET_KEY=$secretKey
CREDENTIAL_STORE_KEY=$credentialStoreKey
"@
Set-Content -Path $EnvPath -Value $envContent -Encoding ASCII

if (!(Test-Path $StartMenuDir)) {
    New-Item -ItemType Directory -Path $StartMenuDir | Out-Null
}

$WshShell = New-Object -ComObject WScript.Shell
$ShortcutTargets = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
    $StartMenuDir
) | Select-Object -Unique

foreach ($ShortcutDir in $ShortcutTargets) {
    if (!(Test-Path $ShortcutDir)) {
        continue
    }

    $ShortcutPath = Join-Path $ShortcutDir "Open-Nexus.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $InstalledExe
    $Shortcut.Arguments = ""
    $Shortcut.WorkingDirectory = $InstallRoot
    $Shortcut.IconLocation = "$InstalledIcon,0"
    $Shortcut.Description = "Abrir Open-Nexus Desktop"
    $Shortcut.Save()
}

if (Test-Path $StartupShortcut) {
    Remove-Item $StartupShortcut -Force -ErrorAction SilentlyContinue
}

Write-Host "Open-Nexus instalado en $InstallRoot"
Write-Host "Accesos directos actualizados."

Start-Process -FilePath $InstalledExe -WorkingDirectory $InstallRoot
