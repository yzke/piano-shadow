[CmdletBinding()]
param(
    [switch]$DemoOnly,
    [switch]$Gpu
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = $PSScriptRoot
$VenvRoot = Join-Path $env:LOCALAPPDATA "PianoShadow\venv"

function Find-CompatiblePython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.10", "3.11")) {
            try {
                $result = & py "-$version" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $result) {
                    return $result.Trim()
                }
            } catch {}
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $result = & python -c "import sys; print(sys.executable if sys.version_info[:2] in [(3,10),(3,11)] else '')"
        if ($result) {
            return $result.Trim()
        }
    }
    throw "Python 3.10/3.11 was not found. Install 64-bit Python 3.10 from python.org."
}

$PythonExe = Find-CompatiblePython
Write-Host "Python: $PythonExe" -ForegroundColor Cyan
Write-Host "Virtual environment: $VenvRoot" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $VenvRoot "Scripts\python.exe"))) {
    New-Item -ItemType Directory -Force -Path (Split-Path $VenvRoot) | Out-Null
    & $PythonExe -m venv $VenvRoot
}

$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
if ($DemoOnly) {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-demo.txt")
} else {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    if ($Gpu -and $LASTEXITCODE -eq 0) {
        & $VenvPython -m pip install torch --index-url https://download.pytorch.org/whl/cu124
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed. See the pip error above."
}

Write-Host ""
Write-Host "Piano Shadow installation completed." -ForegroundColor Green
Write-Host "Demo mode: .\run-windows.ps1 -Demo"
Write-Host "System audio recognition: .\run-windows.ps1"
Write-Host "GPU model install/repair: .\setup-windows.ps1 -Gpu"
