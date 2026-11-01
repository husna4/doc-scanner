"""Muestras sintéticas sin datos personales, reproducibles con esquinas de referencia."""

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DIRECTORY = Path(__file__).parent / "fixtures"
CORNERS = np.array([[260, 90], [840, 170], [920, 900], [140, 830]], dtype=np.float32)


def generate():
    DIRECTORY.mkdir(exist_ok=True)
    font = ImageFont.load_default(size=22)
    with Image.new("RGB", (600, 800), (248, 247, 241)) as page:
        draw = ImageDraw.Draw(page)
        draw.rectangle((35, 35, 565, 42), fill=(41, 101, 91))
        draw.text((40, 65), "DOCUMENTO DE PRUEBA", font=font, fill=(30, 40, 40))
        draw.text(
            (40, 105),
            "Escaneo local - sin datos personales",
            font=ImageFont.load_default(size=15),
            fill=(80, 80, 80),
        )
        for index in range(17):
            y = 170 + index * 29
            draw.text(
                (40, y),
                f"{index + 1:02d}. Texto de ejemplo para verificar el recorte.",
                font=ImageFont.load_default(size=15),
                fill=(35, 35, 35),
            )
        draw.rectangle((40, 710, 200, 750), fill=(195, 108, 65))
        draw.text((450, 735), "PAG. 1", font=font, fill=(30, 40, 40))
        page.save(DIRECTORY / "page.png")
        src = np.array([[0, 0], [599, 0], [599, 799], [0, 799]], dtype=np.float32)
        transform = cv2.getPerspectiveTransform(src, CORNERS)
        warped = cv2.warpPerspective(np.asarray(page), transform, (1100, 1000))
        mask = cv2.warpPerspective(np.full((800, 600), 255, np.uint8), transform, (1100, 1000))
        manifest = {}
        for name in ("inclinado", "sombras", "fondo-complejo"):
            background = Image.new("RGB", (1100, 1000), (55, 67, 65))
            if name == "fondo-complejo":
                drawing = ImageDraw.Draw(background)
                rng = np.random.default_rng(20261101)
                for _ in range(110):
                    x, y = rng.integers(0, [1100, 1000])
                    color = tuple(int(v) for v in rng.integers(30, 145, size=3))
                    drawing.ellipse((int(x), int(y), int(x) + 90, int(y) + 70), fill=color)
                for x in range(0, 1100, 65):
                    drawing.line((x, 0, x + 120, 1000), fill=(95, 87, 65), width=3)
            photo = np.array(background)
            photo[mask > 0] = warped[mask > 0]
            if name == "sombras":
                yy, xx = np.mgrid[:1000, :1100]
                shade = 0.52 + 0.48 * xx / 1099
                shade -= 0.18 * np.exp(-((xx - 430) ** 2 + (yy - 450) ** 2) / 100000)
                photo = np.clip(photo * shade[:, :, None], 0, 255).astype(np.uint8)
            Image.fromarray(photo).save(DIRECTORY / f"{name}.jpg", quality=95)
            manifest[f"{name}.jpg"] = {"corners": CORNERS.tolist(), "size": [1100, 1000]}
        (DIRECTORY / "corners.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    Image.new("RGB", (800, 600), (100, 120, 110)).save(DIRECTORY / "sin-documento.png")


if __name__ == "__main__":
    generate()
