param([int]$Port = 0, [string]$BindAddress = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Primero ejecuta .\scripts\install.ps1' }
    if ($Port -gt 0) { $env:SCANNER_PORT = [string]$Port }
    if ($BindAddress) { $env:SCANNER_HOST = $BindAddress }
    & $pythonExe -m scanner
    if ($LASTEXITCODE -ne 0) { throw 'El servicio ha terminado con un error.' }
} finally { Pop-Location }
