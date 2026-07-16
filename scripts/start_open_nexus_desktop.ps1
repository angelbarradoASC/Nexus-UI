param(
    [switch]$ForceRestart,
    [switch]$PreferSource
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DesktopHost = "127.0.0.1"
$DesktopPort = 11430
$StartupRoute = "/open-nexus"
$HealthUrl = "http://${DesktopHost}:${DesktopPort}/health"
$HealthTimeoutSeconds = 60
$LogsDir = Join-Path $RepoRoot "logs"
$StdoutLog = Join-Path $LogsDir "desktop-launch.out.log"
$StderrLog = Join-Path $LogsDir "desktop-launch.err.log"
$InstalledExe = Join-Path $env:LOCALAPPDATA "Open-Nexus\\OpenNexus.exe"
$DistExe = Join-Path $RepoRoot "dist\\OpenNexus\\OpenNexus.exe"
$BuildExe = Join-Path $RepoRoot "build\\OpenNexus\\OpenNexus.exe"
$DesktopEnvTargets = @(
    (Join-Path $env:LOCALAPPDATA "Open-Nexus\\.env"),
    (Join-Path $env:LOCALAPPDATA "Open-Nexus\\_internal\\.env")
)

function Test-DesktopHealth {
    try {
        $response = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
        if (
            $response.status -eq "ok" -and
            $response.context -eq "desktop_app" -and
            $response.backend -eq "desktop"
        ) {
            return $response
        }
    }
    catch {
    }

    return $null
}

function Get-DesktopProcesses {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -like "python*" -and $_.CommandLine -match "run_preview.py|desktop\.main|desktop\.open_nexus_main") -or
        ($_.Name -eq "OpenNexus.exe")
    }
}

function Stop-DesktopProcesses {
    Get-DesktopProcesses | ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        }
        catch {
        }
    }
}

function Get-PortOwnerDetails {
    $listener = Get-NetTCPConnection -LocalPort $DesktopPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if (-not $listener) {
        return $null
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $process) {
        return [PSCustomObject]@{
            ProcessId = $listener.OwningProcess
            Name = "unknown"
            CommandLine = ""
            IsDesktopCandidate = $false
        }
    }

    $isDesktopCandidate =
        (($process.Name -like "python*") -and ($process.CommandLine -match "run_preview.py|desktop\.main|desktop\.open_nexus_main")) -or
        ($process.Name -eq "OpenNexus.exe")

    return [PSCustomObject]@{
        ProcessId = $process.ProcessId
        Name = $process.Name
        CommandLine = $process.CommandLine
        IsDesktopCandidate = $isDesktopCandidate
    }
}

function Wait-ForDesktopWindow {
    param(
        [int]$ProcessId,
        [int]$TimeoutSeconds = 12
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if (-not $proc) {
            return $false
        }

        if ($proc.MainWindowTitle -eq "Open-Nexus") {
            return $true
        }

        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Get-DesktopLaunchDiagnostics {
    param(
        [System.Diagnostics.Process]$Process
    )

    $windowReady = $false
    if ($Process -and (-not $Process.HasExited)) {
        $windowReady = Wait-ForDesktopWindow -ProcessId $Process.Id -TimeoutSeconds 2
    }

    $stderrTail = ""
    if (Test-Path $StderrLog) {
        $stderrTail = (Get-Content $StderrLog -Tail 40) -join [Environment]::NewLine
    }

    return [PSCustomObject]@{
        WindowReady = $windowReady
        StderrTail = $stderrTail
    }
}

function Resolve-DesktopLauncher {
    $exeCandidates = @($InstalledExe, $DistExe, $BuildExe)
    if (-not $PreferSource) {
        foreach ($candidate in $exeCandidates) {
            if (Test-Path $candidate) {
                return [PSCustomObject]@{
                    FilePath = $candidate
                    Arguments = @()
                    Mode = "packaged"
                    WorkingDirectory = (Split-Path $candidate -Parent)
                }
            }
        }
    }

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $launcherExe = $venvPython
    } else {
        $pythonCommand = Get-Command python -ErrorAction Stop
        $pythonExe = $pythonCommand.Source
        $pythonDir = Split-Path $pythonExe -Parent
        $pythonwExe = Join-Path $pythonDir "pythonw.exe"
        $launcherExe = if (Test-Path $pythonwExe) { $pythonwExe } else { $pythonExe }
    }

    $sourceLauncher = [PSCustomObject]@{
        FilePath = $launcherExe
        Arguments = @("-m", "desktop.main")
        Mode = "source"
        WorkingDirectory = $RepoRoot
    }

    if ($PreferSource -and (Test-Path (Join-Path $RepoRoot "desktop\\main.py"))) {
        return $sourceLauncher
    }

    foreach ($candidate in $exeCandidates) {
        if (Test-Path $candidate) {
            return [PSCustomObject]@{
                FilePath = $candidate
                Arguments = @()
                Mode = "packaged"
                WorkingDirectory = (Split-Path $candidate -Parent)
            }
        }
    }

    return $sourceLauncher
}

function Sync-DesktopEnv {
    $repoEnv = Join-Path $RepoRoot ".env"
    if (!(Test-Path $repoEnv)) {
        return
    }

    foreach ($target in $DesktopEnvTargets) {
        $targetDir = Split-Path -Parent $target
        if (!(Test-Path $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        Copy-Item -Path $repoEnv -Destination $target -Force
    }
}

Push-Location $RepoRoot
try {
    Sync-DesktopEnv

    if (!(Test-Path $LogsDir)) {
        New-Item -ItemType Directory -Path $LogsDir | Out-Null
    }

    if (-not $ForceRestart) {
        $healthy = Test-DesktopHealth
        if ($healthy) {
            Write-Host "Open-Nexus Desktop ya estaba operativo en $HealthUrl"
            return
        }
    }

    $portOwner = Get-PortOwnerDetails
    if ($portOwner) {
        if ($portOwner.IsDesktopCandidate) {
            Stop-Process -Id $portOwner.ProcessId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
        else {
            throw (
                "El puerto $DesktopPort ya esta ocupado por un proceso ajeno. " +
                "PID=$($portOwner.ProcessId) Name=$($portOwner.Name) CommandLine=$($portOwner.CommandLine)"
            )
        }
    }

    Stop-DesktopProcesses
    Start-Sleep -Seconds 1

    if (Test-Path $StdoutLog) {
        Remove-Item $StdoutLog -Force
    }
    if (Test-Path $StderrLog) {
        Remove-Item $StderrLog -Force
    }

    $launcher = Resolve-DesktopLauncher

    $env:NEXUS_CONTEXT = "desktop_app"
    $env:APP_PORT = "$DesktopPort"
    $env:DESKTOP_STARTUP_ROUTE = $StartupRoute
    $env:DEBUG = "false"
    if ($launcher.Mode -eq "source") {
        $pythonPathParts = @($RepoRoot, (Join-Path $RepoRoot "app"))
        if ($env:PYTHONPATH) {
            $pythonPathParts += $env:PYTHONPATH
        }
        $env:PYTHONPATH = ($pythonPathParts -join [IO.Path]::PathSeparator)
    }

    $startProcessParams = @{
        FilePath = $launcher.FilePath
        WorkingDirectory = $launcher.WorkingDirectory
        PassThru = $true
        RedirectStandardOutput = $StdoutLog
        RedirectStandardError = $StderrLog
    }
    if ($launcher.Arguments.Count -gt 0) {
        $startProcessParams.ArgumentList = $launcher.Arguments
    }

    $process = Start-Process @startProcessParams

    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    $healthy = $null
    do {
        Start-Sleep -Milliseconds 700
        $process.Refresh()

        if ($process.HasExited) {
            break
        }

        $healthy = Test-DesktopHealth
        if ($healthy) {
            break
        }
    } while ((Get-Date) -lt $deadline)

    if (-not $healthy) {
        $diagnostics = Get-DesktopLaunchDiagnostics -Process $process

        if (-not $process.HasExited -and $diagnostics.WindowReady) {
            Write-Warning (
                "Open-Nexus ha abierto ventana pero el endpoint /health no respondio " +
                "dentro de ${HealthTimeoutSeconds}s. Se deja el proceso vivo para no cerrarlo " +
                "de forma agresiva. Revisa $StderrLog si la UI no termina de cargar."
            )
        }
        else {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }

            throw (
                "Open-Nexus Desktop no ha quedado sano tras el arranque. " +
                "Revisa $StderrLog." +
                ($(if ($diagnostics.StderrTail) { [Environment]::NewLine + $diagnostics.StderrTail } else { "" }))
            )
        }
    }

    $windowReady = Wait-ForDesktopWindow -ProcessId $process.Id
    if (-not $windowReady) {
        Write-Warning "El backend esta sano en $HealthUrl pero la ventana tardó mas de lo esperado en reportarse."
    }

    Write-Host "Open-Nexus Desktop arrancado correctamente."
    Write-Host "PID: $($process.Id)"
    Write-Host "Health: $HealthUrl"
    Write-Host "Modo de arranque: $($launcher.Mode)"
}
finally {
    Pop-Location
}
