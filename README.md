# DocScanner

Microservicio independiente de escaneo: API REST, editor web en español y exportación JPEG/PDF. Python + FastAPI + OpenCV. Procesamiento local, sin cuentas, claves ni servicios externos.

## Instalación y arranque

Requisitos: Windows, PowerShell y [uv](https://docs.astral.sh/uv/getting-started/installation/). Compatible con Python 3.11–3.13; uv puede descargar el intérprete necesario.

Desde la carpeta del proyecto:

```powershell
.\scripts\install.ps1
.\scripts\start.ps1
```

La instalación utiliza `uv.lock` para fijar las versiones y guarda el entorno y la caché dentro del proyecto. La primera instalación necesita Internet; después, el servicio, el editor y Swagger funcionan sin conexión.

- **Editor:** <http://127.0.0.1:8091/>
- **Swagger:** <http://127.0.0.1:8091/docs>
- **OpenAPI:** <http://127.0.0.1:8091/openapi.json>
- **Estado:** <http://127.0.0.1:8091/health>

Para detener: Ctrl+C. Para otro puerto: `.\scripts\start.ps1 -Port 8092`.
Para seleccionar un intérprete: `.\scripts\install.ps1 -Python '3.12'`.

## Uso del editor

1. Añade fotos o arrástralas al área central. Se preparan en secuencia.
2. Selecciona una página de la lista. La vista **Encuadre** muestra el original corregido por EXIF y cuatro esquinas editables con ratón, táctil o campos de porcentaje.
3. Elige el acabado: **original**, **escala de grises**, **blanco y negro adaptativo** o **documento mejorado**. Gira en pasos de 90° y pulsa **Aplicar ajustes**.
4. Usa las flechas de la lista para reordenar y × para eliminar. Descarga la página como JPEG/PDF o todo el documento como PDF multipágina/JPEG largo.

Si no se encuentra un documento, se conserva el encuadre completo y se omite el filtro automático. Ajusta las esquinas o pulsa **Usar imagen completa** y aplica los ajustes. Se indica explícitamente el resultado de detección.

Los cambios pendientes deben aplicarse antes de exportar. Reprocesar utiliza siempre el archivo original: no acumula compresión por cambiar filtros o esquinas. La exportación PDF incluye exactamente las páginas aplicadas en el orden visible.

## API

Todas las subidas usan `multipart/form-data`. El nombre, la extensión y el MIME declarado no sustituyen la validación del contenido. Se aceptan JPEG, PNG, WebP y HEIC/HEIF fijos; se rechazan animaciones, secuencias, archivos vacíos o corruptos. JPG y JPEG son el mismo formato.

| Método y ruta | Entrada | Salida |
|---|---|---|
| `GET /health` | — | Estado, versión, formatos y límites |
| `POST /api/detect` | `file` | JSON: dimensiones orientadas, `detected`, `corners`, `score` |
| `POST /api/scan` | `file`, opciones siguientes | JPEG, sin EXIF/GPS |
| `POST /api/export/pdf` | Campo `files` repetido y ordenado | PDF A4 multipágina |
| `POST /api/export/image` | `files` repetido, `width` opcional | JPEG vertical |

`/api/scan` acepta:

| Campo | Valor |
|---|---|
| `filter` | `original`, `grayscale`, `bw`, `enhanced` (predeterminado) |
| `rotation` | `0` (predeterminado), `90`, `180`, `270`; sentido horario |
| `auto_crop` | `true` (predeterminado) o `false` |
| `corners` | Cadena JSON de cuatro pares normalizados entre 0 y 1 |

Orden de `corners`: **superior izquierda, superior derecha, inferior derecha, inferior izquierda**. Se refieren a la imagen después de corregir EXIF, antes de aplicar `rotation`. Deben formar un cuadrilátero convexo, no cruzado, con área suficiente. Un punto `(1,1)` identifica el último píxel inferior derecho. Las esquinas manuales prevalecen sobre la detección automática.

Cabeceras JPEG: `X-Scan-Detection` = `detected`, `not_detected`, `manual` o `disabled`; `X-Scan-Filter` indica el filtro realmente aplicado. Ante `not_detected`, devuelve JPEG con el encuadre completo y EXIF corregido; no conserva los bytes originales ni sus metadatos. El giro solicitado sí se aplica.

`score` es una puntuación heurística para diagnóstico, no una probabilidad calibrada.

Los exports reciben **imágenes ya procesadas**; no vuelven a detectar bordes ni aplicar filtros. Una imagen basta para obtener un PDF de una página. El PDF ajusta cada foto sin deformar ni recortar, con orientación A4 por página y margen de 12 puntos. No contiene OCR.

La imagen larga utiliza una anchura común `width` entre 300 y 3000 px (1600 por defecto), conserva la proporción de cada página y las apila sin separación. Puede ampliar páginas pequeñas; usa menos anchura si no quieres ampliarlas. El servidor rechaza dimensiones excesivas antes de reservar el lienzo final.

### Ejemplos con curl.exe (PowerShell)

Los comandos siguientes funcionan con las muestras del proyecto y dejan los resultados dentro de `.runtime/ejemplos`:

```powershell
New-Item -ItemType Directory -Force .runtime\ejemplos | Out-Null

curl.exe http://127.0.0.1:8091/health

curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/detect `
  -F 'file=@tests/fixtures/inclinado.jpg'

curl.exe --fail-with-body -X POST http://127.0.0.1:8091/api/scan `
  -F 'file=@tests/fixtures/inclinado.jpg' -F 'filter=enhanced' `
  -D .runtime/ejemplos/cabeceras.txt -o .runtime/ejemplos/pagina.jpg

# Recorte manual; puntos tras EXIF y giro horario después del recorte.
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

Si curl falla, el archivo de salida puede contener el JSON de error en lugar de una imagen: comprueba su código de salida y la respuesta HTTP.

### Errores

```json
{"error":{"code":"limit_exceeded","message":"Un archivo supera el tamaño máximo permitido."}}
```

- `413`: tamaño, páginas, píxeles, dimensiones o resultado excedidos.
- `415`: formato real no compatible o petición sin multipart.
- `422`: imagen inválida, parámetros, esquinas o formulario incompleto.
- `503`: servicio ocupado; `Retry-After: 2`. Reintentar de forma acotada.
- `500`: error interno, sin incluir contenido de imagen ni traza en la respuesta.

## Configuración

Define variables en la terminal antes de arrancar, por ejemplo `$env:SCANNER_PORT = '8092'`. No se cargan `.env` automáticamente.

| Variable | Predeterminado |
|---|---:|
| `SCANNER_HOST` | `127.0.0.1` |
| `SCANNER_PORT` | `8091` |
| `SCANNER_MAX_FILE_BYTES` | `20971520` (20 MiB) |
| `SCANNER_MAX_REQUEST_BYTES` | `209715200` (200 MiB, incluido multipart) |
| `SCANNER_MAX_PAGES` | `20` |
| `SCANNER_MAX_PIXELS` | `40000000` por imagen |
| `SCANNER_MAX_LONG_PIXELS` | `60000000` para imagen larga |
| `SCANNER_MAX_DIMENSION` | `60000` por lado, máximo configurable 65000 |
| `SCANNER_MAX_CONCURRENCY` | `1` petición de procesamiento/exportación |
| `SCANNER_JPEG_QUALITY` | `92` |

El resultado exportado también está limitado a `SCANNER_MAX_REQUEST_BYTES`. Se verifica el tamaño de petición incluso sin Content-Length. Los archivos se cuentan y limitan durante el análisis multipart. Las dimensiones se consultan antes de cargar los píxeles.

Cada lote se decodifica por páginas. La imagen larga necesita un lienzo completo; el límite de píxeles acota esa reserva. El máximo configurado no es una cuota estricta de RSS: OpenCV, Pillow y PDF pueden utilizar varias copias/buffers. Aumentar píxeles o concurrencia aumenta memoria. Se sirve con un único proceso para que el límite de concurrencia sea global al servicio.

## Archivos, privacidad y acceso

- Sin base de datos ni IDs persistentes. El servidor no mantiene imágenes entre peticiones.
- Los archivos pequeños se procesan en memoria. Los mayores pueden volcarse a temporales propios en `.runtime/uploads`, con borrado al cerrar, también ante errores o desconexión. El arranque limpia restos propios de más de 24 h sin recorrer otras carpetas.
- El navegador mantiene originales y resultados en memoria, sin localStorage/IndexedDB. Se liberan URLs de blobs al reemplazar/eliminar páginas. Cerrar o recargar pierde el documento; descárgalo primero.
- Las descargas solicitadas son archivos persistentes elegidos por el usuario. El navegador controla su carpeta de destino.
- Respuestas `Cache-Control: no-store`; no se registran contenido de imágenes ni nombres de archivo en errores. No se copian EXIF/GPS a JPEG/PDF exportados.
- Por defecto escucha en `127.0.0.1` y no incorpora autenticación.

## Tests

```powershell
.\scripts\test.ps1
# Regenerar las imágenes sintéticas, si se cambia el generador:
.\.venv\Scripts\python.exe -m tests.generate_fixtures
# Medición orientativa y hoja de revisión:
.\.venv\Scripts\python.exe scripts\benchmark.py
```

Fixtures versionadas en `tests/fixtures`: documento inclinado, sombras, fondo complejo, imagen sin documento y página de referencia. `corners.json` contiene sus esquinas conocidas. No incluyen datos personales.

La suite verifica solapamiento del recorte >90 % y error máximo <25 px en las tres fotos de referencia, perspectiva manual, ocho orientaciones EXIF, transparencia, HEIC, filtros, giro, contrato API, orden/orientación PDF, apilado JPEG, tipos falsos, archivos corruptos, límites, peticiones chunked, saturación y limpieza tras éxito/error.

## Organización y límites de v1

```text
scanner/
  api.py          endpoints, validación de opciones y OpenAPI
  processing.py   EXIF, detección, perspectiva y filtros
  export.py       PDF y JPEG largo
  uploads.py      multipart y temporales acotados
  middleware.py   límites de petición y concurrencia
  config.py       configuración por entorno
  static/         editor sin dependencias externas
tests/            fixtures y pruebas de integración/procesamiento
scripts/          instalación, arranque, tests y medición
uv.lock           versiones exactas
```

El detector busca primero bordes y diferencias de luminosidad. Si no encuentra un contorno, intenta distinguir el papel de color neutro de un fondo más saturado. Esto ayuda con recibos en sombra sobre superficies de color. Utiliza el recorte manual si la detección falla con papel oscuro, bordes fuera de la foto, fondos similares o sombras extremas.

No recupera texto borroso, zonas sobreexpuestas ni información tapada. La perspectiva rectifica un plano: no aplana curvatura de libros. EXIF corrige la orientación de cámara; no interpreta el sentido del texto. OCR y PDF con texto seleccionable quedan para una fase futura.
