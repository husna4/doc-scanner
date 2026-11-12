"""API local sin estado. El navegador y Java usan los mismos endpoints multipart."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Literal

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.background import BackgroundTask

from scanner import __version__, export
from scanner.config import ROOT, Settings
from scanner.errors import ScanError, invalid, too_large
from scanner.middleware import ResourceGuard, error_response
from scanner.processing import decode, detect, jpeg, parse_corners, scan
from scanner.uploads import image_form

logger = logging.getLogger("docscanner")
STATIC = Path(__file__).parent / "static"
# https://github.com/swagger-api/swagger-ui/releases/tag/v5.34.1
SWAGGER_STATIC = Path(__file__).parent / "swagger"
ERRORS = {
    code: {
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "message_key": {
                                    "type": "string",
                                    "description": "Optional editor translation key",
                                },
                                "params": {
                                    "type": "object",
                                    "description": "Optional safe named translation parameters",
                                    "additionalProperties": {"type": ["string", "number"]},
                                },
                            },
                        }
                    },
                }
            }
        },
    }
    for code, description in [
        (413, "Límite excedido"),
        (415, "Formato no compatible"),
        (422, "Imagen o parámetros inválidos"),
        (503, "Servicio ocupado"),
        (500, "Error interno"),
    ]
}


class ScanOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: Literal["original", "grayscale", "bw", "enhanced"] = "enhanced"
    rotation: int = 0
    auto_crop: bool = True
    corners: str | None = None

    @field_validator("rotation")
    @classmethod
    def valid_rotation(cls, value):
        if value not in (0, 90, 180, 270):
            raise ValueError("rotation debe ser 0, 90, 180 o 270")
        return value


class ImageOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(default=1600, ge=300, le=3000)


class DetectionResult(BaseModel):
    width: int
    height: int
    detected: bool
    corners: list[list[float]] = Field(description="SI, SD, ID, II; coordenadas [0,1] tras corregir EXIF")
    score: float = Field(description="Puntuación heurística; no es una probabilidad")


def multipart_schema(multiple=False, options=None):
    properties = {
        "files" if multiple else "file": (
            {"type": "array", "items": {"type": "string", "format": "binary"}}
            if multiple
            else {"type": "string", "format": "binary"}
        )
    }
    if options:
        properties.update(options)
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files" if multiple else "file"],
                        "properties": properties,
                        "additionalProperties": False,
                    }
                }
            },
        }
    }


def parameters(form, model, file_field):
    values = {}
    for key, value in form.multi_items():
        if key != file_field:
            if key in values:
                raise invalid(f"El campo '{key}' está repetido.", "errors.repeatedField")
            values[key] = value
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        # No devolver inputs ni nombres de archivos del usuario en los errores.
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise invalid(details, "errors.parameters") from None


class OutputBuffer(SpooledTemporaryFile):
    """Un PDF también tiene límite de bytes; el temporal se elimina al cerrarse."""

    def __init__(self, directory, limit):
        super().__init__(max_size=1024 * 1024, dir=directory, prefix="export-")
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise too_large(
                "El resultado supera el límite de bytes. Divide el documento.", "errors.outputSize"
            )
        return super().write(data)


def chunks(output):
    try:
        while block := output.read(64 * 1024):
            yield block
    finally:
        output.close()


def create_app(settings: Settings | None = None, temp_dir: Path | None = None):
    settings = settings or Settings.from_env()
    directory = (temp_dir or ROOT / ".runtime" / "uploads").resolve()
    if not directory.is_relative_to(ROOT.resolve()):
        raise ValueError("El directorio temporal debe estar dentro del proyecto.")

    @asynccontextmanager
    async def lifespan(application):
        directory.mkdir(parents=True, exist_ok=True)
        # TemporaryFile usa eliminación al cerrar (también al terminar el proceso en Windows).
        # Barrido conservador de restos antiguos, solo archivos propios y sin recursión.
        for pattern in ("upload-*", "export-*"):
            for path in directory.glob(pattern):
                if path.is_file() and not path.is_symlink() and time.time() - path.stat().st_mtime > 86400:
                    try:
                        path.unlink()
                    except OSError:
                        logger.warning("No se pudo limpiar un temporal antiguo.")
        yield

    application = FastAPI(
        title="DocScanner local",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        description=(
            "Escaneo y exportación locales, sin almacenamiento persistente. "
            "Orden de corners: SI, SD, ID, II, normalizadas después de EXIF y antes de rotation. "
            "Los exports reciben imágenes ya procesadas, en el orden de las partes files."
        ),
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.temp_dir = directory
    application.add_middleware(ResourceGuard, settings=settings)
    application.mount("/static", StaticFiles(directory=STATIC), name="static")
    application.mount("/swagger", StaticFiles(directory=SWAGGER_STATIC), name="swagger")

    @application.exception_handler(ScanError)
    async def scan_error(request, error):
        return error_response(error)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(invalid("Los parámetros de la petición no son válidos.", "errors.parameters"))

    @application.exception_handler(Exception)
    async def unexpected_error(request, error):
        logger.error("Fallo interno del escáner (%s)", type(error).__name__)
        return error_response(
            ScanError(500, "internal_error", "No se pudo procesar la imagen.", "errors.internal")
        )

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @application.get("/docs", include_in_schema=False)
    async def docs():
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="DocScanner · API",
            swagger_js_url="/swagger/swagger-ui-bundle.js",
            swagger_css_url="/swagger/swagger-ui.css",
            swagger_favicon_url="/static/favicon.svg",
            swagger_ui_parameters={"validatorUrl": None, "persistAuthorization": False},
        )

    @application.get("/health", summary="Estado y capacidades del servicio")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "processing": "ready",
            "ocr": False,
            "formats": ["JPEG", "PNG", "WEBP", "HEIC", "HEIF"],
            "limits": {
                "file_bytes": settings.max_file_bytes,
                "request_bytes": settings.max_request_bytes,
                "pages": settings.max_pages,
                "pixels": settings.max_pixels,
                "long_pixels": settings.max_long_pixels,
                "dimension": settings.max_dimension,
            },
        }

    @application.post(
        "/api/detect",
        response_model=DetectionResult,
        responses=ERRORS,
        summary="Detectar esquinas del documento",
        openapi_extra=multipart_schema(),
    )
    async def detect_endpoint(request: Request):
        async with image_form(request, settings, directory) as (form, files):
            if any(key != "file" for key in form):
                raise invalid("/api/detect solo admite el campo file.", "errors.detectFields")

            def work():
                with decode(files[0].file, settings) as image:
                    detection = detect(image)
                    return DetectionResult(width=image.width, height=image.height, **vars(detection))

            return await anyio.to_thread.run_sync(work)

    @application.post(
        "/api/scan",
        summary="Recortar, mejorar y rotar una página",
        response_class=Response,
        responses={
            **ERRORS,
            200: {
                "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
                "description": "JPEG (sin EXIF/GPS)",
                "headers": {
                    "X-Scan-Detection": {
                        "schema": {
                            "type": "string",
                            "enum": ["detected", "not_detected", "manual", "disabled"],
                        }
                    },
                    "X-Scan-Filter": {"schema": {"type": "string"}},
                },
            },
        },
        openapi_extra=multipart_schema(
            options={
                "filter": {
                    "type": "string",
                    "enum": ["original", "grayscale", "bw", "enhanced"],
                    "default": "enhanced",
                },
                "rotation": {"type": "integer", "enum": [0, 90, 180, 270], "default": 0},
                "auto_crop": {"type": "boolean", "default": True},
                "corners": {
                    "type": "string",
                    "description": "JSON [[x,y],...] de cuatro esquinas SI,SD,ID,II",
                },
            }
        ),
    )
    async def scan_endpoint(request: Request):
        async with image_form(request, settings, directory) as (form, files):
            options = parameters(form, ScanOptions, "file")
            corners = parse_corners(options.corners)

            def work():
                with decode(files[0].file, settings) as image:
                    result, status, mode = scan(
                        image, options.filter, options.rotation, corners, options.auto_crop, settings
                    )
                    try:
                        content = jpeg(result, settings.jpeg_quality)
                        return content, status, mode
                    finally:
                        if result is not image:
                            result.close()

            content, status, mode = await anyio.to_thread.run_sync(work)
            return Response(
                content,
                media_type="image/jpeg",
                headers={
                    "X-Scan-Detection": status,
                    "X-Scan-Filter": mode,
                    "Content-Disposition": 'inline; filename="pagina.jpg"',
                },
            )

    async def export_endpoint(request, kind):
        async with image_form(request, settings, directory, field="files", multiple=True) as (form, files):
            if kind == "pdf":
                if any(key != "files" for key in form):
                    raise invalid("La exportación PDF solo admite el campo files.", "errors.pdfFields")
                width = None
            else:
                width = parameters(form, ImageOptions, "files").width
            output = OutputBuffer(directory, settings.max_request_bytes)
            try:
                if kind == "pdf":
                    await anyio.to_thread.run_sync(export.pdf, files, settings, output)
                else:
                    await anyio.to_thread.run_sync(export.long_image, files, width, settings, output)
                output.seek(0, 2)
                length = output.tell()
                output.seek(0)
                extension = "pdf" if kind == "pdf" else "jpg"
                return StreamingResponse(
                    chunks(output),
                    media_type=("application/pdf" if kind == "pdf" else "image/jpeg"),
                    headers={
                        "Content-Disposition": f'attachment; filename="documento.{extension}"',
                        "Content-Length": str(length),
                    },
                    background=BackgroundTask(output.close),
                )
            except BaseException:
                output.close()
                raise

    @application.post(
        "/api/export/pdf",
        summary="PDF A4 en orden de entrada",
        response_class=Response,
        responses={
            **ERRORS,
            200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
        },
        openapi_extra=multipart_schema(multiple=True),
    )
    async def pdf_endpoint(request: Request):
        return await export_endpoint(request, "pdf")

    @application.post(
        "/api/export/image",
        summary="JPEG vertical en orden de entrada",
        response_class=Response,
        responses={
            **ERRORS,
            200: {"content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}},
        },
        openapi_extra=multipart_schema(
            multiple=True,
            options={"width": {"type": "integer", "minimum": 300, "maximum": 3000, "default": 1600}},
        ),
    )
    async def image_endpoint(request: Request):
        return await export_endpoint(request, "image")

    return application


app = create_app()
