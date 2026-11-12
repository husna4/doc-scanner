param([string]$Python = '3.11')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.python'
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCommand) { throw 'Instala uv y vuelve a ejecutar este script. / Install uv and run this script again: https://docs.astral.sh/uv/' }
    & $uvCommand.Source sync --locked --python $Python --no-install-project
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias. / Could not install dependencies.' }
    Write-Host 'Instalación completa. Arranca con / Installation complete. Start with: .\scripts\start.ps1'
} finally { Pop-Location }
