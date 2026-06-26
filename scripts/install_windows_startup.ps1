param(
    [string]$ShortcutName = "Nexus Operator.lnk"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$startupFolder = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\Startup"
$installRoot = Join-Path $env:LOCALAPPDATA "Open-Nexus"
$installedExe = Join-Path $installRoot "OpenNexus.exe"
$brandIcon = Join-Path $installRoot "nexus_anchor.ico"
$shortcutPath = Join-Path $startupFolder $ShortcutName

if (!(Test-Path $installedExe)) {
    throw "No se ha encontrado $installedExe. Instala antes Open-Nexus Desktop."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $installedExe
$shortcut.Arguments = ""
$shortcut.WorkingDirectory = $installRoot
$shortcut.IconLocation = if (Test-Path $brandIcon) { "$brandIcon,0" } else { "$installedExe,0" }
$shortcut.Description = "Arranque automatico de Nexus Operator"
$shortcut.Save()

Write-Output "Shortcut instalado en: $shortcutPath"
