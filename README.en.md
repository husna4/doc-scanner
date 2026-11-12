# DocScanner

English · [Español](README.md)

Standalone scanning microservice: REST API, Spanish/English web editor and JPEG/PDF export. Python + FastAPI + OpenCV. Local processing without accounts, keys or external services.

## Installation and startup

### With Docker

Install **Docker Desktop** (includes Compose) or, on Linux, **Docker Engine with Docker Compose**. [Installation options](https://docs.docker.com/compose/install/)

From the project directory, run the same command on Windows or Linux:

```sh
docker compose up --build --wait
```

- **Editor and API base URL** · <http://127.0.0.1:8091/>
- **Swagger** · <http://127.0.0.1:8091/docs>
- **Health** · <http://127.0.0.1:8091/health>

On Windows you can also run `.\scripts\start-docker.cmd`; the launcher displays the URL after startup.

To stop and remove the container, use `docker compose down`.

### Without Docker

Local Windows startup requires PowerShell and [uv](https://docs.astral.sh/uv/getting-started/installation/). Python 3.11–3.13 is supported; uv can download the required interpreter.

From the project directory:

```powershell
.\scripts\install.ps1
.\scripts\start.ps1
```

Installation uses `uv.lock` to pin versions and keeps the environment and cache inside the project. The first installation requires Internet access; afterwards the service, editor and Swagger work offline.

- **Editor:** <http://127.0.0.1:8091/>
- **Swagger:** <http://127.0.0.1:8091/docs>
- **OpenAPI:** <http://127.0.0.1:8091/openapi.json>
- **Health:** <http://127.0.0.1:8091/health>

To stop: Ctrl+C. For a different port: `.\scripts\start.ps1 -Port 8092`.
To choose an interpreter: `.\scripts\install.ps1 -Python '3.12'`.

## Using the editor

The header's **Language** selector offers **Español** and **English**, without reloading or processing photos again. A valid saved preference (`es` or `en`) takes priority, followed by the first supported language in `navigator.languages` (with `navigator.language` as a fallback), then English if none match. Regional variants such as `es-MX` and `en-GB` are recognized. Manual choices are saved only in `localStorage`, under `docscanner.language`. If storage is blocked, the choice stays in memory while the page remains open. The selector is disabled during operations and corner dragging. Swagger has its own interface and is outside the editor's language selector.

1. Add photos or drag them into the central area. They are prepared sequentially.
2. Select a page from the list. **Crop** shows the EXIF-corrected original and four corners editable with a mouse, touch or percentage fields.
3. Choose a finish: **original**, **grayscale**, **adaptive black and white** or **enhanced document**. Rotate in 90° steps and choose **Apply settings**.
4. Use the list arrows to reorder and × to delete. Download a page as JPEG/PDF or the whole document as a multipage PDF/long JPEG.

If no document is found, the full frame is kept and the automatic filter is skipped. Adjust the corners or choose **Use full image**, then apply settings. The detection outcome is shown explicitly.

Pending settings must be applied before exporting. Processing always uses the original file, so changing filters or corners does not accumulate compression. PDF export contains exactly the applied pages in the visible order.

## API

All uploads use `multipart/form-data`. Names, extensions and declared MIME types do not replace content validation. Still JPEG, PNG, WebP and HEIC/HEIF images are supported; animations, sequences, empty and corrupt files are rejected. JPG and JPEG are the same format.

| Method and path | Input | Output |
|---|---|---|
| `GET /health` | — | Status, version, formats and limits |
| `POST /api/detect` | `file` | JSON: oriented dimensions, `detected`, `corners`, `score` |
| `POST /api/scan` | `file`, options below | JPEG without EXIF/GPS |
| `POST /api/export/pdf` | Repeated, ordered `files` field | Multipage A4 PDF |
| `POST /api/export/image` | Repeated `files`, optional `width` | Vertical JPEG |

`/api/scan` accepts:

| Field | Value |
|---|---|
| `filter` | `original`, `grayscale`, `bw`, `enhanced` (default) |
| `rotation` | `0` (default), `90`, `180`, `270`; clockwise |
| `auto_crop` | `true` (default) or `false` |
| `corners` | JSON string of four normalized pairs between 0 and 1 |

`corners` order: **top left, top right, bottom right, bottom left**. Coordinates refer to the image after EXIF correction, before `rotation`. They must form a convex, non-crossed quadrilateral with sufficient area. A point `(1,1)` identifies the last bottom-right pixel. Manual corners override automatic detection.

JPEG headers: `X-Scan-Detection` = `detected`, `not_detected`, `manual` or `disabled`; `X-Scan-Filter` indicates the filter actually applied. For `not_detected`, the response is a full-frame JPEG with corrected EXIF orientation; original bytes and metadata are not preserved. Requested rotation still applies.

`score` is a diagnostic heuristic score, not a calibrated probability.

Exports receive **already processed images**; they do not detect edges or apply filters again. One image is enough for a single-page PDF. The PDF fits each photo without distortion or cropping, with A4 orientation chosen per page and a 12-point margin. It contains no OCR.

Long images use a common `width` between 300 and 3000 px (1600 by default), preserve each page's aspect ratio and stack them without gaps. Small pages may be upscaled; use a smaller width to avoid this. The server rejects excessive dimensions before allocating the final canvas.

### curl.exe examples (PowerShell)

These commands use the project's sample images and save results inside `.runtime/ejemplos`:

```powershell
New-Item -ItemType Directory -Force .runtime\ejemplos | Out-Null

curl.exe http://127.0.0.1:8091/health

curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/detect `
  -F 'file=@tests/fixtures/inclinado.jpg'

curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/scan `
  -F 'file=@tests/fixtures/inclinado.jpg' -F 'filter=enhanced' `
  -D .runtime/ejemplos/cabeceras.txt -o .runtime/ejemplos/pagina.jpg

# Manual crop; points after EXIF, clockwise rotation after cropping.
curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/scan `
  -F 'file=@tests/fixtures/inclinado.jpg' -F 'filter=grayscale' -F 'rotation=90' `
  -F 'corners=[[0.237,0.090],[0.764,0.170],[0.837,0.901],[0.127,0.831]]' `
  -o .runtime/ejemplos/manual.jpg

curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/export/pdf `
  -F 'files=@.runtime/ejemplos/pagina.jpg' -F 'files=@.runtime/ejemplos/manual.jpg' `
  -o .runtime/ejemplos/documento.pdf

curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/export/image `
  -F 'files=@.runtime/ejemplos/pagina.jpg' -F 'files=@.runtime/ejemplos/manual.jpg' `
  -F 'width=1600' -o .runtime/ejemplos/documento-largo.jpg
```

If curl fails, the output file may contain error JSON instead of an image: check its exit code and HTTP response.

### Errors

```json
{"error":{"code":"limit_exceeded","message":"Un archivo supera el tamaño máximo permitido.","message_key":"errors.fileSize"}}
```

- `413`: file size, pages, pixels, dimensions or output limit exceeded.
- `415`: unsupported actual format or request without multipart.
- `422`: invalid image, parameters, corners or incomplete form.
- `503`: service busy; `Retry-After: 2`. Use bounded retries.
- `500`: internal error, without image content or a traceback in the response.

HTTP statuses, `error.code` and `error.message` retain their existing contract. Optional `error.message_key` and `error.params` fields add safe metadata for browser translation. Existing clients can ignore them. Pydantic validation details remain in the API; the editor shows a localized invalid-parameters message. No language is sent to the server.

## Configuration

For startup without Docker, set variables in the terminal, for example `$env:SCANNER_PORT = '8092'`. The application does not load `.env` automatically. If port 8091 is occupied, set `DOCSCANNER_PORT` in the environment used to run Docker Compose to change the published port. To change scanner limits in Docker, add the appropriate `SCANNER_*` variables to the service's `environment` in `compose.yaml`.

| Variable | Default |
|---|---:|
| `SCANNER_HOST` | `127.0.0.1` |
| `SCANNER_PORT` | `8091` |
| `SCANNER_MAX_FILE_BYTES` | `20971520` (20 MiB) |
| `SCANNER_MAX_REQUEST_BYTES` | `209715200` (200 MiB, including multipart) |
| `SCANNER_MAX_PAGES` | `20` |
| `SCANNER_MAX_PIXELS` | `40000000` per image |
| `SCANNER_MAX_LONG_PIXELS` | `60000000` for a long image |
| `SCANNER_MAX_DIMENSION` | `60000` per side, configurable maximum 65000 |
| `SCANNER_MAX_CONCURRENCY` | `1` processing/export request |
| `SCANNER_JPEG_QUALITY` | `92` |

Export output is also limited to `SCANNER_MAX_REQUEST_BYTES`. Request size is checked even without Content-Length. Files are counted and limited while parsing multipart. Dimensions are checked before loading pixels.

Each batch is decoded page by page. A long image needs a complete canvas; the pixel limit bounds that allocation. The configured maximum is not a strict RSS quota: OpenCV, Pillow and PDF processing can use several copies/buffers. Increasing pixels or concurrency increases memory usage. The service runs in a single process so its concurrency limit applies to the whole service.

## Files, privacy and access

- No database or persistent IDs. The server does not retain images between requests.
- Small files are processed in memory. Larger files may spill to owned temporary files in `.runtime/uploads`, deleted on close, including errors or disconnections. Startup removes owned leftovers older than 24 hours without traversing other directories.
- The browser keeps originals and results only in memory, without saving them in localStorage/IndexedDB. `localStorage` stores only the language preference (`docscanner.language`: `es` or `en`). Blob URLs are released when pages are replaced or deleted. Closing or reloading loses the document; download it first.
- Requested downloads are persistent files chosen by the user. The browser controls the destination folder.
- Responses use `Cache-Control: no-store`; image content and filenames are not logged in errors. EXIF/GPS metadata is not copied to exported JPEG/PDF files.
- By default the service listens on `127.0.0.1` and has no authentication.

## Tests

```powershell
.\scripts\test.ps1
# Regenerate synthetic images if the generator changes:
.\.venv\Scripts\python.exe -m tests.generate_fixtures
# Indicative benchmark and review sheet:
.\.venv\Scripts\python.exe scripts\benchmark.py
```

Versioned fixtures in `tests/fixtures`: inclined document, shadows, complex background, image without a document and reference page. `corners.json` contains their known corners. They contain no personal data.

The suite checks crop overlap >90% and maximum error <25 px on the three reference photos, manual perspective, eight EXIF orientations, transparency, HEIC, filters, rotation, API contract, PDF order/orientation, JPEG stacking, false types, corrupt files, limits, chunked requests, saturation and cleanup after success/error.

Catalog and error compatibility tests are part of the regular suite. To also test the editor in real Chromium, install the optional development group and browser (Internet is required the first time):

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.cache\uv'
uv sync --locked --group browser --no-install-project
.\.venv\Scripts\python.exe -m playwright install chromium
.\scripts\test.ps1 --editor
# Browser tests only:
.\.venv\Scripts\python.exe -m pytest tests/browser --editor
```

Playwright is not required to install or start the app and is not installed in the Docker image. Without `--editor`, browser tests are explicitly skipped. They start their own service on an available local port and check both languages, data preservation and locks, notices, blocked storage, complete operations, absence of external requests and JavaScript errors. Desktop (1440 px) and mobile (375 px) screenshots with visible coordinate fields are saved under `.runtime/pytest/browser*/editor-*.png` for visual review. These tests use Chromium; other engines and physical devices are not covered.

## Translations

`scanner/static/i18n.js` loads local `locales/es.json` and `locales/en.json` catalogs before the editor. `t(key, params)` interpolates named parameters and falls back to English for missing keys. Static text uses `data-i18n` on text elements; allowed attributes are `data-i18n-title`, `data-i18n-alt` and `data-i18n-aria-label`. Do not mark containers containing controls or icons: mark a text `span` to preserve their children.

To add a message, include the same semantic key and parameters in both JSON files. Store states and notices as keys with data, without already translated sentences. To add another language, copy the English catalog, translate its values without changing keys or parameters, register its code in `i18n.js` (loading, resolution and selection), add its accessible header option and extend catalog, resolution and browser tests. New error keys must also be added at their server origins; use only safe parameters. Do not translate multipart values, filenames, paths or download names.

## Organization

```text
scanner/
  api.py          endpoints, option validation and OpenAPI
  processing.py   EXIF, detection, perspective and filters
  export.py       PDF and long JPEG
  uploads.py      bounded multipart and temporary files
  middleware.py   request and concurrency limits
  config.py       environment configuration
  static/         editor without external dependencies
tests/            fixtures and integration/processing tests
scripts/          installation, startup, tests and benchmarking
uv.lock           exact versions
```
