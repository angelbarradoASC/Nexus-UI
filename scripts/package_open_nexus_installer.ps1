$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $RepoRoot "dist\OpenNexus"
$VerifyScript = Join-Path $RepoRoot "scripts\verify_open_nexus_build.ps1"
$ReleaseRoot = Join-Path $RepoRoot "release"
$StageRoot = Join-Path $ReleaseRoot "OpenNexus-Installer"
$OutputExe = Join-Path $ReleaseRoot "OpenNexus-Setup.exe"
$SedPath = Join-Path $StageRoot "OpenNexusInstaller.sed"
$PayloadZip = Join-Path $StageRoot "payload.zip"
$ClientInstallScript = Join-Path $RepoRoot "scripts\install_open_nexus_client.ps1"
$ClientInstallCmd = Join-Path $StageRoot "install_open_nexus_client.cmd"
$IExpress = Join-Path $env:WINDIR "System32\iexpress.exe"

if (!(Test-Path $IExpress)) {
    throw "No se ha encontrado iexpress.exe en este equipo."
}

& $VerifyScript

if (Test-Path $StageRoot) {
    Remove-Item $StageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $StageRoot | Out-Null

Compress-Archive -Path (Join-Path $DistRoot '*') -DestinationPath $PayloadZip -Force
Copy-Item $ClientInstallScript (Join-Path $StageRoot "install_open_nexus_client.ps1") -Force

$cmdContent = @'
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_open_nexus_client.ps1"
'@
Set-Content -Path $ClientInstallCmd -Value $cmdContent -Encoding ASCII

$quotedOutput = '"' + $OutputExe.Replace('"', '""') + '"'
$payloadSizeKb = [math]::Ceiling((Get-Item $PayloadZip).Length / 1KB) + 1024

$sedContent = @"
[Version]
Class=IExpress
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ExtractOnly=0
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=1
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
ShowRebootUI=0
PackageInstallSpace=$payloadSizeKb
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=<None>
AdminQuietInstCmd=%AppLaunched%
UserQuietInstCmd=%AppLaunched%
SourceFiles=SourceFiles
Strings=Strings
[SourceFiles]
SourceFiles0=$StageRoot
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
[Strings]
TargetName=$quotedOutput
FriendlyName="Open-Nexus Desktop"
AppLaunched="cmd.exe /c install_open_nexus_client.cmd"
FILE0="payload.zip"
FILE1="install_open_nexus_client.ps1"
FILE2="install_open_nexus_client.cmd"
"@

Set-Content -Path $SedPath -Value $sedContent -Encoding ASCII

$iexpressProcess = Start-Process `
    -FilePath $IExpress `
    -ArgumentList @("/N", $SedPath) `
    -PassThru `
    -Wait

if ($iexpressProcess.ExitCode -ne 0) {
    throw "IExpress ha fallado con código $($iexpressProcess.ExitCode)."
}

if (!(Test-Path $OutputExe)) {
    throw "IExpress no ha generado $OutputExe"
}

Write-Host "Instalador generado en $OutputExe"
