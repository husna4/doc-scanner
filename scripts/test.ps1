$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Primero ejecuta .\scripts\install.ps1' }
    & $pythonExe -m pytest --basetemp=.runtime/pytest @args
    if ($LASTEXITCODE -ne 0) { throw 'Hay tests fallidos.' }
    & $pythonExe -m ruff check scanner tests scripts/benchmark.py
    if ($LASTEXITCODE -ne 0) { throw 'Hay problemas de análisis estático.' }
} finally { Pop-Location }
