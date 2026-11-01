import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scanner.api import create_app
from scanner.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    (Path(__file__).resolve().parent.parent / ".runtime").mkdir(exist_ok=True)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(), tmp_path / "uploads")) as connection:
        yield connection


@pytest.fixture
def inclined():
    return (FIXTURES / "inclinado.jpg").read_bytes()


def image_bytes(color="white", size=(120, 160), format="PNG", **kwargs):
    output = io.BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(output, format, **kwargs)
    return output.getvalue()
