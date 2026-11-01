import io
import json

import cv2
import numpy as np
import pytest
from PIL import Image

from scanner.config import Settings
from scanner.errors import ScanError
from scanner.processing import apply_filter, decode, detect, jpeg, parse_corners, scan, warp
from tests.conftest import FIXTURES, image_bytes


@pytest.mark.parametrize("name", ["inclinado", "sombras", "fondo-complejo"])
def test_detection_overlaps_annotated_document(name):
    manifest = json.loads((FIXTURES / "corners.json").read_text())
    with Image.open(FIXTURES / f"{name}.jpg") as image:
        result = detect(image)
        assert result.detected
        actual = np.array(result.corners, np.float32) * [image.width - 1, image.height - 1]
        expected = np.array(manifest[f"{name}.jpg"]["corners"], np.float32)
        actual = actual.astype(np.float32)
        intersection, _ = cv2.intersectConvexConvex(actual, expected)
        union = cv2.contourArea(actual) + cv2.contourArea(expected) - intersection
        assert intersection / union > 0.90
        assert np.linalg.norm(actual - expected, axis=1).max() < 25


def test_manual_perspective_restores_page_without_background(inclined):
    settings = Settings()
    with decode(io.BytesIO(inclined), settings) as image:
        corners = (np.array([[260, 90], [840, 170], [920, 900], [140, 830]]) / [1099, 999]).tolist()
        with warp(image, corners, settings) as result:
            assert 750 < result.width < 810
            assert 730 < result.height < 800
            pixels = np.asarray(result)
            assert pixels[15:35, 15:35].mean() > 220
            assert pixels[-25:-5, -25:-5].mean() > 220


def test_no_document_preserves_full_frame_and_does_not_apply_filter():
    with Image.open(FIXTURES / "sin-documento.png") as image:
        assert not detect(image).detected
        result, status, mode = scan(image, "bw", 0, None, True, Settings())
        assert result.size == image.size
        assert np.array_equal(np.asarray(result), np.asarray(image))
        assert status == "not_detected" and mode == "original"


@pytest.mark.parametrize(
    "orientation, expected",
    [
        (1, (120, 160)),
        (2, (120, 160)),
        (3, (120, 160)),
        (4, (120, 160)),
        (5, (160, 120)),
        (6, (160, 120)),
        (7, (160, 120)),
        (8, (160, 120)),
    ],
)
def test_all_exif_orientations_and_metadata_removed(orientation, expected):
    image = Image.new("RGB", (120, 160), "white")
    image.paste("red", (0, 0, 30, 40))
    exif = Image.Exif()
    exif[274] = orientation
    data = io.BytesIO()
    image.save(data, "JPEG", exif=exif)
    with decode(data, Settings()) as result:
        assert result.size == expected
        from PIL import ImageOps

        data.seek(0)
        with Image.open(data) as source:
            expected_image = ImageOps.exif_transpose(source).convert("RGB")
            assert np.array_equal(np.asarray(result), np.asarray(expected_image))
        with Image.open(io.BytesIO(jpeg(result, 92))) as encoded:
            assert not encoded.getexif()


def test_transparency_is_white():
    data = io.BytesIO()
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(data, "PNG")
    with decode(data, Settings()) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_heic_round_trip():
    data = image_bytes("orange", format="HEIF")
    with decode(io.BytesIO(data), Settings()) as image:
        assert image.size == (120, 160)
        assert image.mode == "RGB"


def test_filters_and_shadow_reduction():
    with Image.open(FIXTURES / "page.png") as image:
        gray = np.asarray(apply_filter(image, "grayscale"))
        assert np.array_equal(gray[:, :, 0], gray[:, :, 1])
        assert np.array_equal(gray[:, :, 1], gray[:, :, 2])
        binary = np.asarray(apply_filter(image, "bw"))
        assert set(np.unique(binary)).issubset({0, 255})
    gradient = np.tile(np.linspace(90, 240, 600), (800, 1))
    rgb = np.repeat(gradient[:, :, None], 3, axis=2).astype(np.uint8)
    enhanced = np.asarray(apply_filter(Image.fromarray(rgb), "enhanced"))
    assert enhanced.std() < rgb.std() * 0.5


@pytest.mark.parametrize(
    "rotation, expected", [(0, (120, 160)), (90, (160, 120)), (180, (120, 160)), (270, (160, 120))]
)
def test_clockwise_rotation(rotation, expected):
    image = Image.new("RGB", (120, 160), "white")
    image.paste("red", (0, 0, 30, 40))
    result, _, _ = scan(image, "original", rotation, None, False, Settings())
    assert result.size == expected
    assert np.array_equal(np.asarray(result), np.asarray(image.rotate(-rotation, expand=True)))


@pytest.mark.parametrize(
    "corners",
    [
        "[]",
        "null",
        "oops",
        "[[0,0],[1,1],[1,0],[0,1]]",
        "[[0,0],[0,1],[1,1],[1,0]]",
        "[[0,0],[2,0],[1,1],[0,1]]",
        "[[0,0],[1,0],[1,0],[0,1]]",
        "[[0,0],[NaN,0],[1,1],[0,1]]",
        '[["0",0],[1,0],[1,1],[0,1]]',
        "[[false,0],[1,0],[1,1],[0,1]]",
    ],
)
def test_invalid_corners_rejected(corners):
    with pytest.raises(ScanError, match="corners"):
        parse_corners(corners)


def test_pixel_limit_before_load():
    with pytest.raises(ScanError) as result:
        decode(io.BytesIO(image_bytes(size=(200, 200))), Settings(max_pixels=1000))
    assert result.value.status == 413
