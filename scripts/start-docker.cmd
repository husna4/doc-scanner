@echo off
setlocal EnableExtensions DisableDelayedExpansion

where.exe docker.exe >nul 2>&1
if errorlevel 1 (
    >&2 echo Instala e inicia Docker Desktop con contenedores Linux y vuelve a ejecutar el script.
    exit /b 1
)

pushd "%~dp0.." || exit /b 1
docker.exe compose up --build --wait --wait-timeout 60
if errorlevel 1 (
    >&2 echo DocScanner no ha arrancado. Revisa la salida de Docker o ejecuta docker compose logs docscanner.
    popd
    exit /b 1
)

set "endpoint="
for /f "delims=" %%A in ('docker.exe compose port docscanner 8091') do set "endpoint=%%A"
popd
if not defined endpoint (
    >&2 echo No se pudo consultar el puerto publicado de DocScanner.
    exit /b 1
)

echo Editor y URL base de la API: http://%endpoint%/
echo Swagger: http://%endpoint%/docs
exit /b 0
