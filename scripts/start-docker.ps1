$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command docker -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'Instala e inicia Docker Desktop con contenedores Linux y vuelve a ejecutar el script.'
}

Push-Location $projectRoot
try {
    docker compose up --build --wait --wait-timeout 60
    if ($LASTEXITCODE -ne 0) {
        throw 'DocScanner no ha arrancado. Revisa la salida de Docker y ejecuta docker compose logs docscanner desde la carpeta del proyecto.'
    }

    $endpoint = docker compose port docscanner 8091
    if ($LASTEXITCODE -ne 0 -or -not $endpoint) {
        throw 'No se pudo consultar el puerto publicado de DocScanner.'
    }

    Write-Host "Editor y URL base de la API: http://$endpoint/"
    Write-Host "Swagger: http://$endpoint/docs"
} finally {
    Pop-Location
}
