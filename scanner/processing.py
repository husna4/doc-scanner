"""Decodificación, geometría y filtros. No almacena imágenes ni conoce HTTP."""

import io
import json
import warnings
from dataclasses import dataclass
from typing import BinaryIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from scanner.config import Settings
from scanner.errors import ScanError, invalid, too_large

register_heif_opener()
cv2.setNumThreads(1)
FILTERS = ("original", "grayscale", "bw", "enhanced")
FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


def decode(source: BinaryIO, settings: Settings) -> Image.Image:
    """Consulta dimensiones antes de cargar píxeles y aplica las ocho orientaciones EXIF."""
    try:
        source.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if image.format not in FORMATS:
                    raise ScanError(
                        415, "unsupported_format", "Usa JPEG, PNG, WebP o HEIC/HEIF.", "errors.format"
                    )
                width, height = image.size
                if width * height > settings.max_pixels or max(width, height) > settings.max_dimension:
                    raise too_large(
                        "La imagen supera el límite de píxeles o dimensiones.", "errors.imageDimensions"
                    )
                if min(width, height) < 32:
                    raise invalid("La imagen debe medir al menos 32 × 32 píxeles.", "errors.imageSmall")
                if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1:
                    raise invalid(
                        "Sube una imagen fija por página, sin animación ni secuencias.", "errors.animation"
                    )
                oriented = ImageOps.exif_transpose(image)
                if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    rgb = Image.new("RGB", rgba.size, "white")
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                    return rgb
                # No propagar EXIF/GPS al resultado.
                return oriented.convert("RGB").copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise too_large(
            "La imagen supera el límite seguro de descompresión.", "errors.decompression"
        ) from None
    except UnidentifiedImageError:
        raise ScanError(
            415, "unsupported_format", "El contenido no es una imagen compatible.", "errors.contentFormat"
        ) from None
    except (OSError, ValueError, SyntaxError) as exc:
        raise invalid("La imagen está dañada o no se puede decodificar.", "errors.decode") from exc


def normalized(points: np.ndarray, width: int, height: int) -> list[list[float]]:
    return np.clip(points / np.array([width - 1, height - 1]), 0, 1).round(6).tolist()


def order_points(points: np.ndarray) -> np.ndarray:
    """Orden circular, empezando por la esquina más próxima a superior izquierda."""
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    points = points[np.argsort(angles)]
    return np.roll(points, -np.argmin(points.sum(axis=1)), axis=0)


@dataclass
class Detection:
    detected: bool
    corners: list[list[float]]
    score: float


def detect(image: Image.Image) -> Detection:
    """Combina bordes y regiones claras; no considera el borde del marco un documento."""
    width, height = image.size
    scale = min(1.0, 1400 / max(width, height))
    small = np.asarray(image.resize((round(width * scale), round(height * scale))))
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 45, 130)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, light = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    best, score = _find_document((edges, light), gray)
    if best is None:
        # El papel neutro puede distinguirse de un fondo de color incluso bajo sombras.
        saturation = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)[:, :, 1]
        saturation = cv2.GaussianBlur(saturation, (9, 9), 0)
        threshold, _ = cv2.threshold(saturation, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, paper = cv2.threshold(saturation, min(threshold, 35), 255, cv2.THRESH_BINARY_INV)
        paper[blur < 70] = 0
        paper = cv2.morphologyEx(paper, cv2.MORPH_CLOSE, np.ones((19, 19), np.uint8))
        best, score = _find_document((paper,), cv2.bitwise_not(saturation))
    if best is None:
        return Detection(False, [[0, 0], [1, 0], [1, 1], [0, 1]], 0.0)
    sh, sw = gray.shape
    return Detection(True, normalized(best, sw, sh), round(score, 3))


def _find_document(masks, contrast_channel):
    sh, sw = contrast_channel.shape
    best, best_score = None, 0.0
    for mask in masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
            area = cv2.contourArea(contour)
            coverage = area / (sw * sh)
            if not 0.08 <= coverage <= 0.97:
                continue
            perimeter = cv2.arcLength(contour, True)
            for epsilon in (0.015, 0.025, 0.04):
                quad = cv2.approxPolyDP(contour, epsilon * perimeter, True)
                if len(quad) != 4 or not cv2.isContourConvex(quad):
                    continue
                points = order_points(quad)
                lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
                if min(lengths) < 0.12 * min(sw, sh) or max(lengths) / min(lengths) > 8:
                    continue
                on_frame = (
                    (points[:, 0] < 3)
                    | (points[:, 0] > sw - 4)
                    | (points[:, 1] < 3)
                    | (points[:, 1] > sh - 4)
                )
                if on_frame.sum() > 1:
                    continue
                inside = np.zeros_like(contrast_channel)
                cv2.fillConvexPoly(inside, points.astype(np.int32), 255)
                inner = cv2.erode(inside, np.ones((11, 11), np.uint8))
                ring = cv2.subtract(cv2.dilate(inside, np.ones((19, 19), np.uint8)), inside)
                if not np.any(inner) or not np.any(ring):
                    continue
                contrast = cv2.mean(contrast_channel, inner)[0] - cv2.mean(contrast_channel, ring)[0]
                if contrast < 10:
                    continue
                solidity = min(area / max(cv2.contourArea(quad), 1), 1.0)
                score = coverage * 0.65 + min(contrast / 100, 1) * 0.25 + solidity * 0.1
                if score > best_score:
                    best, best_score = points, score
    return best, best_score


def parse_corners(value: str | None) -> list[list[float]] | None:
    if value is None:
        return None
    try:
        data = json.loads(value)
        if not isinstance(data, list) or any(
            not isinstance(pair, list) or len(pair) != 2 or any(type(v) not in (int, float) for v in pair)
            for pair in data
        ):
            raise ValueError
        points = np.asarray(data, dtype=np.float64)
        if points.shape != (4, 2) or not np.isfinite(points).all() or np.any((points < 0) | (points > 1)):
            raise ValueError
        edges = np.roll(points, -1, axis=0) - points
        cross = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
        area = cv2.contourArea(points.astype(np.float32))
        if not np.all(cross > 0.0001) or area < 0.005:
            raise ValueError
        return points.tolist()
    except (ValueError, TypeError, json.JSONDecodeError):
        raise invalid(
            "corners: cuatro puntos normalizados [x,y], convexos, en orden SI, SD, ID, II.", "errors.corners"
        ) from None


def warp(image: Image.Image, corners: list[list[float]], settings: Settings) -> Image.Image:
    points = np.asarray(corners, dtype=np.float32) * (np.array(image.size, np.float32) - 1)
    tl, tr, br, bl = points
    width = max(round(float(np.linalg.norm(tr - tl))), round(float(np.linalg.norm(br - bl)))) + 1
    height = max(round(float(np.linalg.norm(bl - tl))), round(float(np.linalg.norm(br - tr)))) + 1
    if min(width, height) < 32:
        raise invalid("El recorte debe medir al menos 32 × 32 píxeles.", "errors.cropSmall")
    if width * height > settings.max_pixels or max(width, height) > settings.max_dimension:
        raise too_large("El recorte supera las dimensiones permitidas.", "errors.cropDimensions")
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(points, target)
    result = cv2.warpPerspective(np.asarray(image), matrix, (width, height), flags=cv2.INTER_CUBIC)
    return Image.fromarray(result)


def apply_filter(image: Image.Image, mode: str) -> Image.Image:
    if mode == "original":
        return image
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if mode == "grayscale":
        return Image.fromarray(gray).convert("RGB")
    if mode == "bw":
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        block = min(51, min(gray.shape) // 2 * 2 - 1)
        binary = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 13
        )
        return Image.fromarray(binary).convert("RGB")
    # Estimar iluminación a resolución reducida evita kernels costosos en fotos de 40 MP.
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    lum, a, b = cv2.split(lab)
    ratio = min(1, 1200 / max(lum.shape))
    small = cv2.resize(lum, (round(lum.shape[1] * ratio), round(lum.shape[0] * ratio)))
    kernel = max(31, (min(small.shape) // 12) | 1)
    # El cierre elimina texto y pequeñas zonas oscuras antes de estimar las sombras.
    # Un kernel rectangular usa la implementación separable y evita halos en sellos.
    background = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    background = cv2.GaussianBlur(background, (0, 0), 19)
    background = cv2.resize(background, (lum.shape[1], lum.shape[0]))
    clean = cv2.divide(lum, np.maximum(background, 1), scale=240)
    clean = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(clean)
    return Image.fromarray(cv2.cvtColor(cv2.merge((clean, a, b)), cv2.COLOR_LAB2RGB))


def scan(image, mode, rotation, corners, auto_crop, settings):
    manual = corners is not None
    detection = detect(image) if auto_crop and not manual else None
    selected = corners if manual else detection.corners if detection and detection.detected else None
    status = "manual" if manual else "detected" if selected else "not_detected" if auto_crop else "disabled"
    result = warp(image, selected, settings) if selected else image
    applied_filter = mode if status != "not_detected" else "original"
    result = apply_filter(result, applied_filter)
    if rotation:
        result = result.rotate(-rotation, expand=True)
    return result, status, applied_filter


def jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, subsampling=0)
    return buffer.getvalue()
