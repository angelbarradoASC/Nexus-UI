param(
    [string]$ShortcutName = "Nexus Operator.lnk"
)

$startupFolder = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\Startup"
$shortcutPath = Join-Path $startupFolder $ShortcutName

if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Output "Shortcut eliminado: $shortcutPath"
} else {
    Write-Output "No existe shortcut en: $shortcutPath"
}
