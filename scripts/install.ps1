param([string]$Python = '3.11')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.python'
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCommand) { throw 'Instala uv (https://docs.astral.sh/uv/) y vuelve a ejecutar este script.' }
    & $uvCommand.Source sync --locked --python $Python --no-install-project
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
    Write-Host 'Instalación completa. Arranca con: .\scripts\start.ps1'
} finally { Pop-Location }
