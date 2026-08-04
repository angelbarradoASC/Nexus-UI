$ErrorActionPreference = "Stop"

Write-Host "Instalando Open-Nexus..."
Write-Host "Se preparara un runtime local y un ejecutable empaquetado."

$RepoRoot = Split-Path -Parent $PSScriptRoot
$InstallRoot = Join-Path $env:LOCALAPPDATA "Open-Nexus"
$BuildScript = Join-Path $RepoRoot "scripts\build_open_nexus.ps1"
$InstalledExe = Join-Path $InstallRoot "OpenNexus.exe"
$InstalledIcon = Join-Path $InstallRoot "nexus_anchor.ico"

function Set-OpenNexusShortcut {
    param(
        [string]$ShortcutPath
    )

    $ShortcutDir = Split-Path -Parent $ShortcutPath
    if (!(Test-Path $ShortcutDir)) {
        New-Item -ItemType Directory -Path $ShortcutDir -Force | Out-Null
    }

    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $InstalledExe
    $Shortcut.Arguments = ""
    $Shortcut.WorkingDirectory = $InstallRoot
    $Shortcut.IconLocation = "$InstalledExe,0"
    $Shortcut.Description = "Abrir Open-Nexus Desktop"
    $Shortcut.Save()
}

function Stop-OpenNexusProcesses {
    $desktopProcesses = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "OpenNexus.exe" -or
        (
            $_.Name -like "python*" -and
            $_.CommandLine -match "run_preview.py|desktop.main"
        )
    }

    foreach ($process in $desktopProcesses) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
        }
    }

    if ($desktopProcesses) {
        Start-Sleep -Seconds 2
    }
}

if (!(Test-Path $InstallRoot)) {
    New-Item -ItemType Directory -Path $InstallRoot | Out-Null
}

& powershell -ExecutionPolicy Bypass -File $BuildScript

$DistRoot = Join-Path $RepoRoot "dist\OpenNexus"
if (!(Test-Path $DistRoot)) {
    throw "No existe dist\\OpenNexus. El build no ha generado artefactos."
}

Stop-OpenNexusProcesses

Copy-Item "$DistRoot\*" $InstallRoot -Recurse -Force
Copy-Item (Join-Path $RepoRoot "products\desktop\ui\static\nexus_anchor.ico") $InstalledIcon -Force

$WshShell = New-Object -ComObject WScript.Shell
$ShortcutTargets = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop")
) | Select-Object -Unique

foreach ($DesktopDir in $ShortcutTargets) {
    if (!(Test-Path $DesktopDir)) {
        continue
    }

    foreach ($ShortcutName in @("Open-Nexus.lnk", "Open-Nexus Desktop.lnk")) {
        Set-OpenNexusShortcut -ShortcutPath (Join-Path $DesktopDir $ShortcutName)
    }

    Get-ChildItem -Path $DesktopDir -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("Open-Nexus.lnk", "Open-Nexus Desktop.lnk") } |
        ForEach-Object {
            Set-OpenNexusShortcut -ShortcutPath $_.FullName
        }
}

$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Open-Nexus"
foreach ($ShortcutName in @("Open-Nexus.lnk", "Open-Nexus Desktop.lnk")) {
    Set-OpenNexusShortcut -ShortcutPath (Join-Path $StartMenuDir $ShortcutName)
}

$TaskbarPinnedDir = Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
if (Test-Path $TaskbarPinnedDir) {
    foreach ($PinnedName in @("Open-Nexus Desktop.lnk", "Open-Nexus.lnk")) {
        $PinnedShortcutPath = Join-Path $TaskbarPinnedDir $PinnedName
        if (!(Test-Path $PinnedShortcutPath)) {
            continue
        }

        Set-OpenNexusShortcut -ShortcutPath $PinnedShortcutPath
    }
}

Write-Host ""
Write-Host "Open-Nexus instalado en $InstallRoot"
Write-Host "Accesos directos creados en los escritorios detectados."
