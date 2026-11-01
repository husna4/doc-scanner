"""Exportación secuencial de páginas: no decodifica un lote completo a la vez."""

import io
import math

from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from scanner.errors import too_large
from scanner.processing import decode


def pdf(files, settings, output):
    document = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    document.setTitle("Documento escaneado")
    document.setCreator("DocScanner local")
    for uploaded in files:
        with decode(uploaded.file, settings) as image:
            page_w, page_h = landscape(A4) if image.width > image.height else A4
            document.setPageSize((page_w, page_h))
            margin = 12
            factor = min((page_w - 2 * margin) / image.width, (page_h - 2 * margin) / image.height)
            width, height = image.width * factor, image.height * factor
            # JPEG directo para incrustar sin guardar PNGs intermedios ni retener píxeles del lote.
            encoded = io.BytesIO()
            image.save(encoded, "JPEG", quality=settings.jpeg_quality)
            encoded.seek(0)
            document.drawImage(
                ImageReader(encoded), (page_w - width) / 2, (page_h - height) / 2, width=width, height=height
            )
            document.showPage()
    document.save()
    output.seek(0)


def long_image(files, width, settings, output):
    heights = []
    # Primera pasada: dimensiones verificadas antes de reservar el lienzo de salida.
    for uploaded in files:
        with decode(uploaded.file, settings) as image:
            heights.append(max(1, math.ceil(image.height * width / image.width)))
    height = sum(heights)
    if width * height > settings.max_long_pixels or max(width, height) > settings.max_dimension:
        raise too_large("La imagen larga supera el límite. Reduce su anchura o exporta a PDF.")
    with Image.new("RGB", (width, height), "white") as combined:
        y = 0
        for uploaded, page_height in zip(files, heights, strict=True):
            with decode(uploaded.file, settings) as image:
                with image.resize((width, page_height), Image.Resampling.LANCZOS) as page:
                    combined.paste(page, (0, y))
            y += page_height
        combined.save(output, "JPEG", quality=settings.jpeg_quality)
    output.seek(0)
