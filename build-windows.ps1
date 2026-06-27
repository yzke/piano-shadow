[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $env:LOCALAPPDATA "PianoShadow\venv\Scripts\python.exe"
$BuildRoot = Join-Path $env:LOCALAPPDATA "PianoShadow\package-build"
$DistRoot = Join-Path $ProjectRoot "dist"

if (-not (Test-Path $VenvPython)) {
    throw "Windows environment is not installed. Run setup-windows.ps1 first."
}

if (Test-Path $BuildRoot) {
    Remove-Item -Recurse -Force $BuildRoot
}
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
Copy-Item (Join-Path $ProjectRoot "*.py") $BuildRoot

& $VenvPython -m pip install "pyinstaller>=6.10,<7"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller installation failed."
}

Push-Location $BuildRoot
try {
    & $VenvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "PianoShadow-Windows-x64" `
        --collect-all basic_pitch `
        --collect-all soundcard `
        --collect-submodules onnxruntime `
        --exclude-module torch `
        --exclude-module torchlibrosa `
        --exclude-module piano_transcription_inference `
        --exclude-module matplotlib `
        --exclude-module tkinter `
        main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
    Copy-Item `
        (Join-Path $BuildRoot "dist\PianoShadow-Windows-x64.exe") `
        (Join-Path $DistRoot "PianoShadow-Windows-x64.exe") `
        -Force
} finally {
    Pop-Location
}

Write-Host "Built: $(Join-Path $DistRoot 'PianoShadow-Windows-x64.exe')" -ForegroundColor Green
