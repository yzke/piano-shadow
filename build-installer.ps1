[CmdletBinding()]
param(
    [string]$Version = "0.6.4",
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ExePath = Join-Path $ProjectRoot "dist\PianoShadow-v$Version-Windows-x64.exe"
$InstallerPath = Join-Path $ProjectRoot "dist\PianoShadow-Setup-v$Version-Windows-x64.exe"

if (-not $SkipExeBuild) {
    & (Join-Path $ProjectRoot "build-windows.ps1") -Version $Version
    if ($LASTEXITCODE -ne 0) {
        throw "Application EXE build failed."
    }
}
if (-not (Test-Path $ExePath)) {
    throw "Application EXE not found: $ExePath"
}

$IsccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 was not found. Install it with: winget install JRSoftware.InnoSetup"
}

Push-Location $ProjectRoot
try {
    & $Iscc `
        "/DAppVersion=$Version" `
        "/DSourceExe=$ExePath" `
        (Join-Path $ProjectRoot "installer.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
} finally {
    Pop-Location
}

Write-Host "Built installer: $InstallerPath" -ForegroundColor Green
