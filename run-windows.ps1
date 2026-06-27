[CmdletBinding()]
param(
    [switch]$Demo,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$VenvPython = Join-Path $env:LOCALAPPDATA "PianoShadow\venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Windows environment is not installed. Run: .\setup-windows.ps1"
}

Push-Location $PSScriptRoot
try {
    $Arguments = @("main.py")
    if ($Demo) {
        $Arguments += "--demo-mode"
    }
    if ($ExtraArgs) {
        $Arguments += $ExtraArgs
    }
    & $VenvPython @Arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
