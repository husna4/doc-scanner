import ast
import asyncio
import json
import re
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scanner.api import OutputBuffer, create_app
from scanner.config import Settings
from scanner.errors import ScanError, invalid, too_large
from scanner.middleware import ResourceGuard, error_response
from tests.conftest import image_bytes

STATIC = Path(__file__).resolve().parents[1] / "scanner" / "static"
CATALOGS = {
    code: json.loads((STATIC / f"locales/{code}.json").read_text(encoding="utf-8")) for code in ("es", "en")
}


def test_catalog_keys_parameters_and_static_references():
    assert CATALOGS["es"].keys() == CATALOGS["en"].keys()
    for key, value in CATALOGS["en"].items():
        assert value and CATALOGS["es"][key]
        assert set(re.findall(r"\{(\w+)\}", value)) == set(re.findall(r"\{(\w+)\}", CATALOGS["es"][key])), key
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for key in re.findall(r'data-i18n(?:-[\w-]+)?="([^"]+)"', html):
        assert key in CATALOGS["en"], key
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    for key in re.findall(
        r'"((?:status|errors|notices|busy|corners|connection|actions|pages)\.\w+)"', source
    ):
        assert key in CATALOGS["en"], key
    # Every server error call has explicit metadata, including Pydantic's dynamic detail.
    for filename in ("api.py", "middleware.py", "uploads.py", "processing.py", "export.py"):
        tree = ast.parse((STATIC.parent / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("invalid", "too_large", "ScanError"):
                    index = 3 if node.func.id == "ScanError" else 1
                    assert len(node.args) > index, (filename, node.lineno)
                    assert node.args[index].value in CATALOGS["en"]


@pytest.mark.parametrize("resource", ["i18n.js", "locales/es.json", "locales/en.json"])
def test_local_resources(client, resource):
    response = client.get(f"/static/{resource}")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]


def check_error(response, status, code, message, key, params=None):
    assert response.status_code == status
    expected = {"code": code, "message": message, "message_key": key}
    if params is not None:
        expected["params"] = params
    assert response.json() == {"error": expected}


def test_legacy_error_constructors_and_optional_metadata():
    for error in (ScanError(422, "legacy", "unchanged"), invalid("unchanged"), too_large("unchanged")):
        assert json.loads(error_response(error).body) == {
            "error": {"code": error.code, "message": "unchanged"}
        }
    error = invalid("unchanged", "errors.missingFile", {"field": "file"})
    assert json.loads(error_response(error).body)["error"]["params"] == {"field": "file"}


@pytest.mark.parametrize(
    "endpoint,files,data,status,code,message,key,params",
    [
        (
            "scan",
            {"file": ("photo.jpg", b"bad")},
            {},
            415,
            "unsupported_format",
            "El contenido no es una imagen compatible.",
            "errors.contentFormat",
            None,
        ),
        (
            "scan",
            {"file": ("empty.jpg", b"")},
            {},
            422,
            "invalid_image_or_parameters",
            "No se aceptan archivos vacíos.",
            "errors.emptyFile",
            None,
        ),
        (
            "scan",
            {"other": ("p.png", image_bytes())},
            {},
            422,
            "invalid_image_or_parameters",
            "Incluye al menos una imagen en el campo 'file'.",
            "errors.missingFile",
            {"field": "file"},
        ),
        (
            "detect",
            {"file": ("p.png", image_bytes())},
            {"bad": "x"},
            422,
            "invalid_image_or_parameters",
            "/api/detect solo admite el campo file.",
            "errors.detectFields",
            None,
        ),
        (
            "export/pdf",
            {"files": ("p.png", image_bytes())},
            {"bad": "x"},
            422,
            "invalid_image_or_parameters",
            "La exportación PDF solo admite el campo files.",
            "errors.pdfFields",
            None,
        ),
        (
            "scan",
            {"file": ("p.png", image_bytes(size=(10, 10)))},
            {},
            422,
            "invalid_image_or_parameters",
            "La imagen debe medir al menos 32 × 32 píxeles.",
            "errors.imageSmall",
            None,
        ),
        (
            "scan",
            {"file": ("p.bmp", image_bytes(format="BMP"))},
            {},
            415,
            "unsupported_format",
            "Usa JPEG, PNG, WebP o HEIC/HEIF.",
            "errors.format",
            None,
        ),
    ],
)
def test_api_error_contract(client, endpoint, files, data, status, code, message, key, params):
    check_error(client.post(f"/api/{endpoint}", files=files, data=data), status, code, message, key, params)


def test_validation_preserves_detail_without_exposing_it_as_translation(client):
    response = client.post("/api/scan", files={"file": ("p.png", image_bytes())}, data={"rotation": "45"})
    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "invalid_image_or_parameters"
    assert error["message"] == "rotation: Value error, rotation debe ser 0, 90, 180 o 270"
    assert error["message_key"] == "errors.parameters"
    assert "params" not in error


def test_distinct_limit_metadata(tmp_path):
    settings = replace(
        Settings(), max_file_bytes=1000, max_request_bytes=5000, max_long_pixels=10_000, max_pixels=20_000
    )
    with TestClient(create_app(settings, tmp_path / "limits")) as client:
        cases = [
            ("scan", b"x" * 1001, 413, "Un archivo supera el tamaño máximo permitido.", "errors.fileSize"),
            (
                "scan",
                b"x" * 6000,
                413,
                "La petición supera el tamaño máximo permitido.",
                "errors.requestSize",
            ),
            (
                "scan",
                image_bytes(size=(150, 150)),
                413,
                "La imagen supera el límite de píxeles o dimensiones.",
                "errors.imageDimensions",
            ),
            (
                "export/image",
                image_bytes(),
                413,
                "La imagen larga supera el límite. Reduce su anchura o exporta a PDF.",
                "errors.longImage",
            ),
        ]
        for route, content, status, message, key in cases:
            field = "files" if route.startswith("export/") else "file"
            check_error(
                client.post(f"/api/{route}", files={field: ("p.png", content)}),
                status,
                "limit_exceeded",
                message,
                key,
            )
        check_error(
            client.post("/api/scan", json={}),
            415,
            "multipart_required",
            "Envía las imágenes como multipart/form-data.",
            "errors.multipartRequired",
        )
    with OutputBuffer(tmp_path, 1) as output:
        with pytest.raises(ScanError) as raised:
            output.write(b"ab")
        assert raised.value.message == "El resultado supera el límite de bytes. Divide el documento."
        assert raised.value.message_key == "errors.outputSize"


def test_middleware_metadata_and_release(tmp_path):
    async def unused(scope, receive, send):
        raise AssertionError("Request should have been rejected by the middleware")

    guard = ResourceGuard(unused, replace(Settings(), max_request_bytes=100))

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=guard), base_url="http://test"
        ) as client:
            for value in ("bad", "-1"):
                check_error(
                    await client.post("/api/scan", headers={"Content-Length": value}),
                    422,
                    "invalid_length",
                    "Content-Length no válido.",
                    "errors.contentLength",
                )
                assert guard.active == 0
            check_error(
                await client.post("/api/scan", content=b"x" * 101),
                413,
                "limit_exceeded",
                "La petición supera el tamaño máximo permitido.",
                "errors.requestSize",
            )
            assert guard.active == 0
            guard.active = 1
            response = await client.post("/api/scan")
            check_error(
                response, 503, "busy", "El escáner está ocupado. Reintenta en unos segundos.", "errors.busy"
            )
            assert response.headers["Retry-After"] == "2"
            guard.active = 0

    asyncio.run(exercise())


def test_internal_error_and_openapi(tmp_path, monkeypatch):
    import scanner.api as api

    def fail(image):
        raise RuntimeError("internal secret")

    monkeypatch.setattr(api, "detect", fail)
    with TestClient(create_app(Settings(), tmp_path / "internal"), raise_server_exceptions=False) as client:
        response = client.post("/api/detect", files={"file": ("p.png", image_bytes())})
        check_error(response, 500, "internal_error", "No se pudo procesar la imagen.", "errors.internal")
        assert "secret" not in response.text
        schema = client.get("/openapi.json").json()
        for route in ("detect", "scan", "export/pdf", "export/image"):
            for status in ("413", "415", "422", "500", "503"):
                error = schema["paths"][f"/api/{route}"]["post"]["responses"][status]["content"][
                    "application/json"
                ]["schema"]["properties"]["error"]
                assert error["required"] == ["code", "message"]
                assert {"message_key", "params"} <= error["properties"].keys()
