import asyncio
import io
import threading
from dataclasses import replace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from scanner.api import create_app
from scanner.config import Settings
from tests.conftest import FIXTURES, image_bytes


def test_health_home_and_offline_swagger(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "Tu papel, en limpio" in client.get("/").text
    docs = client.get("/docs")
    assert "cdn.jsdelivr" not in docs.text
    assert "/swagger/swagger-ui-bundle.js" in docs.text
    assert client.get("/swagger/swagger-ui-bundle.js").status_code == 200
    assert client.get("/swagger/swagger-ui.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    schema = client.get("/openapi.json").json()
    for route in ("/api/detect", "/api/scan", "/api/export/pdf", "/api/export/image"):
        assert "multipart/form-data" in schema["paths"][route]["post"]["requestBody"]["content"]
    assert "image/jpeg" in schema["paths"]["/api/scan"]["post"]["responses"]["200"]["content"]


def test_detect_scan_and_manual_override(client, inclined):
    detection = client.post("/api/detect", files={"file": ("photo.jpg", inclined)}).json()
    assert detection["detected"] and len(detection["corners"]) == 4
    automatic = client.post("/api/scan", files={"file": ("photo.jpg", inclined)}, data={"filter": "original"})
    assert automatic.status_code == 200
    assert automatic.headers["x-scan-detection"] == "detected"
    assert "no-store" in automatic.headers["cache-control"]
    assert automatic.headers["x-content-type-options"] == "nosniff"
    manual = client.post(
        "/api/scan",
        files={"file": ("photo.jpg", inclined)},
        data={"corners": "[[0,0],[1,0],[1,1],[0,1]]", "filter": "grayscale", "rotation": "90"},
    )
    assert manual.status_code == 200
    assert manual.headers["x-scan-detection"] == "manual"
    with Image.open(io.BytesIO(manual.content)) as image:
        assert image.size == (1000, 1100)
        a = np.asarray(image)
        assert np.abs(a[:, :, 0].astype(int) - a[:, :, 1]).max() <= 2


def test_no_detection_is_successful_fallback(client):
    data = (FIXTURES / "sin-documento.png").read_bytes()
    result = client.post("/api/scan", files={"file": ("photo.png", data)}, data={"filter": "bw"})
    assert result.status_code == 200
    assert result.headers["x-scan-detection"] == "not_detected"
    assert result.headers["x-scan-filter"] == "original"
    with Image.open(io.BytesIO(result.content)) as image:
        assert image.size == (800, 600)
        assert 95 < image.getpixel((100, 100))[0] < 105


@pytest.mark.parametrize("mode", ["original", "grayscale", "bw", "enhanced"])
def test_filter_without_crop_is_explicitly_available(client, mode):
    response = client.post(
        "/api/scan",
        files={"file": ("photo.png", image_bytes("orange"))},
        data={"auto_crop": "false", "filter": mode},
    )
    assert response.status_code == 200
    assert response.headers["x-scan-detection"] == "disabled"
    assert response.headers["x-scan-filter"] == mode


def test_pdf_page_count_orientation_and_order(client):
    files = [
        ("files", ("red.png", image_bytes("red", (120, 160)))),
        ("files", ("blue.png", image_bytes("blue", (200, 100)))),
    ]
    response = client.post("/api/export/pdf", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    pages = PdfReader(io.BytesIO(response.content)).pages
    assert len(pages) == 2
    assert pages[0].mediabox.height > pages[0].mediabox.width
    assert pages[1].mediabox.width > pages[1].mediabox.height
    for index, color_channel in [(0, 0), (1, 2)]:
        image = pages[index].images[0].image.convert("RGB")
        assert image.getpixel((30, 30))[color_channel] > 240
        assert image.getpixel((30, 30))[(color_channel + 1) % 3] < 15


def test_long_jpeg_keeps_order_and_proportions(client):
    response = client.post(
        "/api/export/image",
        files=[
            ("files", ("blue.png", image_bytes("blue", (100, 100)))),
            ("files", ("red.png", image_bytes("red", (100, 200)))),
        ],
        data={"width": "300"},
    )
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (300, 900)
        assert image.getpixel((100, 100))[2] > 240
        assert image.getpixel((100, 500))[0] > 240


@pytest.mark.parametrize(
    "fields",
    [
        {"filter": "magic"},
        {"rotation": "45"},
        {"auto_crop": "perhaps"},
        {"corners": "[[0,0],[1,1],[1,0],[0,1]]"},
        {"unexpected": "x"},
    ],
)
def test_invalid_parameters(client, fields):
    response = client.post("/api/scan", files={"file": ("photo.png", image_bytes())}, data=fields)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image_or_parameters"


@pytest.mark.parametrize("data", [b"MZ-not-an-image", b"%PDF-1.4", b"<svg></svg>"])
def test_disguised_file_rejected_by_content(client, data):
    response = client.post("/api/scan", files={"file": ("photo.jpg", data, "image/jpeg")})
    assert response.status_code == 415


def test_truncated_image_and_empty_upload(client):
    corrupt = image_bytes()[:60]
    result = client.post("/api/detect", files={"file": ("photo.png", corrupt)})
    assert result.status_code in (415, 422)
    result = client.post("/api/detect", files={"file": ("empty.jpg", b"")})
    assert result.status_code == 422


def test_unsupported_decodable_file_and_animation(client):
    bmp = client.post("/api/scan", files={"file": ("photo.jpg", image_bytes(format="BMP"))})
    assert bmp.status_code == 415
    frames = [Image.new("RGB", (64, 64), color) for color in ["red", "blue"]]
    output = io.BytesIO()
    frames[0].save(output, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    result = client.post("/api/scan", files={"file": ("animation.webp", output.getvalue())})
    assert result.status_code == 422


def test_wrong_form_or_missing_files(client):
    assert client.post("/api/scan", json={"file": "no"}).status_code == 415
    assert client.post("/api/scan", files={"wrong": ("photo.png", image_bytes())}).status_code == 422
    response = client.post("/api/export/pdf", files={"files": ("page.png", image_bytes())}, data={"bad": "x"})
    assert response.status_code == 422


def test_size_page_and_long_image_limits(tmp_path):
    settings = replace(
        Settings(), max_file_bytes=1000, max_request_bytes=5000, max_pages=2, max_long_pixels=100_000
    )
    with TestClient(create_app(settings, tmp_path / "limits")) as client:
        assert client.post("/api/scan", files={"file": ("large.jpg", b"x" * 1001)}).status_code == 413
        assert client.post("/api/scan", files={"file": ("large.jpg", b"x" * 6000)}).status_code == 413
        files = [("files", ("page.png", image_bytes()))] * 3
        assert client.post("/api/export/pdf", files=files).status_code == 413
        response = client.post("/api/export/image", files=files[:1], data={"width": "1600"})
        assert response.status_code == 413
        assert client.post("/api/export/image", files=files[:1], data={"width": "299"}).status_code == 422


def test_temporary_files_closed_after_success_and_partial_failure(client, monkeypatch):
    import scanner.uploads as uploads

    original = uploads.SpooledTemporaryFile
    opened = []

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        opened.append(result)
        return result

    monkeypatch.setattr(uploads, "SpooledTemporaryFile", tracked)
    # Ruido PNG >1 MiB fuerza volcado a disco; el fichero malo llega en segundo lugar.
    pixels = np.random.default_rng(42).integers(0, 255, (800, 800, 3), dtype=np.uint8)
    data = io.BytesIO()
    Image.fromarray(pixels).save(data, "PNG")
    good = data.getvalue()
    assert len(good) > 1024 * 1024
    success = client.post(
        "/api/scan", files={"file": ("noise.png", good)}, data={"auto_crop": "false", "filter": "original"}
    )
    assert success.status_code == 200
    error = client.post(
        "/api/export/pdf", files=[("files", ("noise.png", good)), ("files", ("invalid.jpg", b"not-image"))]
    )
    assert error.status_code == 415
    assert len(opened) == 3 and all(item.closed for item in opened)
    assert not list(client.app.state.temp_dir.iterdir())


def test_incomplete_multipart_closes_created_files(client, monkeypatch):
    import scanner.uploads as uploads

    original = uploads.SpooledTemporaryFile
    opened = []

    def tracked(*args, **kwargs):
        item = original(*args, **kwargs)
        opened.append(item)
        return item

    monkeypatch.setattr(uploads, "SpooledTemporaryFile", tracked)
    partial = b'--abc\r\nContent-Disposition: form-data; name="file"; filename="photo.png"\r\n\r\nxxx'
    result = client.post(
        "/api/scan", content=partial, headers={"Content-Type": "multipart/form-data; boundary=abc"}
    )
    assert result.status_code == 422
    assert opened and all(item.closed for item in opened)


def test_chunked_limit_without_content_length(tmp_path):
    app = create_app(replace(Settings(), max_request_bytes=500), tmp_path / "chunked")

    async def exercise():
        async def body():
            yield b'--abc\r\nContent-Disposition: form-data; name="file"; filename="photo.png"\r\n\r\n'
            yield b"x" * 700
            yield b"\r\n--abc--\r\n"

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/scan", content=body(), headers={"Content-Type": "multipart/form-data; boundary=abc"}
                )
                assert response.status_code == 413
                assert not list(app.state.temp_dir.iterdir())

    asyncio.run(exercise())


def test_busy_response_and_health_remains_responsive(tmp_path, monkeypatch):
    import scanner.api as api

    original = api.detect
    started, release = threading.Event(), threading.Event()

    def blocked(image):
        started.set()
        assert release.wait(10)
        return original(image)

    monkeypatch.setattr(api, "detect", blocked)
    app = create_app(Settings(), tmp_path / "busy")

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = asyncio.create_task(
                    client.post("/api/detect", files={"file": ("a.png", image_bytes())})
                )
                try:
                    for _ in range(100):
                        if started.is_set():
                            break
                        await asyncio.sleep(0.01)
                    assert started.is_set()
                    second = await client.post("/api/detect", files={"file": ("b.png", image_bytes())})
                    assert second.status_code == 503 and second.headers["Retry-After"] == "2"
                    assert (await client.get("/health")).status_code == 200
                finally:
                    release.set()
                assert (await first).status_code == 200
                assert (
                    await client.post("/api/detect", files={"file": ("c.png", image_bytes())})
                ).status_code == 200

    asyncio.run(exercise())
