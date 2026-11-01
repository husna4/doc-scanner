"""Configuración explícita, sin modificar variables globales del equipo."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def integer(name: str, default: int, minimum: int = 1, maximum: int = 2**40) -> int:
    value = int(os.getenv(f"SCANNER_{name}", str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"SCANNER_{name} debe estar entre {minimum} y {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8091
    max_file_bytes: int = 20 * 1024 * 1024
    max_request_bytes: int = 200 * 1024 * 1024
    max_pages: int = 20
    max_pixels: int = 40_000_000
    max_long_pixels: int = 60_000_000
    max_dimension: int = 60_000
    max_concurrency: int = 1
    jpeg_quality: int = 92

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("SCANNER_HOST", "127.0.0.1"),
            port=integer("PORT", 8091, 1, 65535),
            max_file_bytes=integer("MAX_FILE_BYTES", 20 * 1024 * 1024),
            max_request_bytes=integer("MAX_REQUEST_BYTES", 200 * 1024 * 1024),
            max_pages=integer("MAX_PAGES", 20, 1, 100),
            max_pixels=integer("MAX_PIXELS", 40_000_000),
            max_long_pixels=integer("MAX_LONG_PIXELS", 60_000_000),
            max_dimension=integer("MAX_DIMENSION", 60_000, 64, 65000),
            max_concurrency=integer("MAX_CONCURRENCY", 1, 1, 8),
            jpeg_quality=integer("JPEG_QUALITY", 92, 50, 100),
        )
