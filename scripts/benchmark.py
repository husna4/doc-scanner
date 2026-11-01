"""Medición orientativa y hoja de revisión visual. No accede a fotos del usuario."""

import io
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import psutil
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scanner.config import ROOT, Settings  # noqa: E402
from scanner.processing import decode, detect, jpeg, scan  # noqa: E402


def measure(data):
    process = psutil.Process()
    baseline = process.memory_info().rss
    peaks = [baseline]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.01):
            peaks.append(process.memory_info().rss)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    times = []
    try:
        for _ in range(3):
            start = time.perf_counter()
            with decode(io.BytesIO(data), Settings()) as image:
                result, status, _ = scan(image, "enhanced", 0, None, True, Settings())
                jpeg(result, 92)
                result.close()
            times.append(time.perf_counter() - start)
            peaks.append(process.memory_info().rss)
    finally:
        stop.set()
        sampler.join()
    return {
        "median_seconds": round(statistics.median(times), 3),
        "samples_seconds": [round(value, 3) for value in times],
        "baseline_rss_mib": round(baseline / 1048576, 1),
        "sampled_peak_rss_mib": round(max(peaks) / 1048576, 1),
        "detection": status,
    }


def main():
    directory = ROOT / "test-results"
    directory.mkdir(exist_ok=True)
    font = ImageFont.load_default(size=18)
    sheet = Image.new("RGB", (1200, 1100), "#f5f3ee")
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (25, 15), "DocScanner | muestras originales, esquinas y resultado mejorado", fill="#153f3e", font=font
    )
    report = {"python": sys.version.split()[0], "platform": sys.platform, "samples": {}}
    for index, name in enumerate(("inclinado", "sombras", "fondo-complejo")):
        path = ROOT / "tests" / "fixtures" / f"{name}.jpg"
        data = path.read_bytes()
        report["samples"][name] = measure(data)
        with decode(io.BytesIO(data), Settings()) as original:
            detection = detect(original)
            annotated = original.copy()
            points = [(x * (original.width - 1), y * (original.height - 1)) for x, y in detection.corners]
            ImageDraw.Draw(annotated).line(points + points[:1], fill="#ed8b39", width=8)
            result, _, _ = scan(original, "enhanced", 0, None, True, Settings())
            for column, image in enumerate((original, annotated, result)):
                image.thumbnail((365, 300))
                sheet.paste(image, (25 + column * 395, 100 + index * 330))
            result.close()
            draw.text((25, 65 + index * 330), name, fill="#153f3e", font=font)
    with Image.open(ROOT / "tests" / "fixtures" / "inclinado.jpg") as source:
        large = source.resize((3300, 3000), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        large.save(buffer, "JPEG", quality=92)
        large.close()
    report["samples"]["9.9-megapixels"] = measure(buffer.getvalue())
    report["limitations"] = (
        "Tres ejecuciones por muestra sintética, en el mismo proceso. RSS total muestreado "
        "cada 10 ms; incluye librerías y memoria retenida. No es benchmark concurrente ni SLA."
    )
    sheet.save(directory / "processing-review.jpg", quality=92)
    (directory / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
