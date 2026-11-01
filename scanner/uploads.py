"""Multipart acotado: temporales propios y cierre también ante desconexión o error."""

from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import SpooledTemporaryFile

from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from scanner.config import Settings
from scanner.errors import ScanError, invalid, too_large


class LimitedParser(MultiPartParser):
    # Este adaptador usa hooks de Starlette: uv.lock fija la versión y los tests cubren su limpieza.
    def __init__(self, request, settings: Settings, directory: Path, count: int):
        super().__init__(request.headers, request.stream(), max_files=count, max_fields=8, max_part_size=8192)
        self.settings = settings
        self.directory = directory
        self.part_bytes = 0
        self.header_bytes = 0
        self.finished = False

    def on_part_begin(self):
        super().on_part_begin()
        self.part_bytes = self.header_bytes = 0

    def on_header_field(self, data, start, end):
        self.header_bytes += end - start
        self.check_headers()
        super().on_header_field(data, start, end)

    def on_header_value(self, data, start, end):
        self.header_bytes += end - start
        self.check_headers()
        super().on_header_value(data, start, end)

    def check_headers(self):
        if self.header_bytes > 16384:
            raise too_large("Las cabeceras multipart son demasiado grandes.")

    def on_headers_finished(self):
        super().on_headers_finished()
        if self._current_part.file:
            old = self._current_part.file.file
            own = SpooledTemporaryFile(max_size=1024 * 1024, dir=self.directory, prefix="upload-")
            self._current_part.file.file = own
            self._files_to_close_on_error[-1] = own
            old.close()

    def on_part_data(self, data, start, end):
        self.part_bytes += end - start
        if self._current_part.file and self.part_bytes > self.settings.max_file_bytes:
            raise too_large("Un archivo supera el tamaño máximo permitido.")
        super().on_part_data(data, start, end)

    def on_end(self):
        self.finished = True


@asynccontextmanager
async def image_form(request, settings, directory, field="file", multiple=False):
    if request.headers.get("content-type", "").split(";")[0].lower() != "multipart/form-data":
        raise ScanError(415, "multipart_required", "Envía las imágenes como multipart/form-data.")
    parser = LimitedParser(request, settings, directory, settings.max_pages if multiple else 1)
    form = None
    try:
        try:
            form = await parser.parse()
        except MultiPartException as exc:
            if "Too many" in exc.message or "exceeded" in exc.message:
                raise too_large("Demasiados archivos/campos o un campo supera el límite.") from exc
            raise invalid("El formulario multipart no es válido.") from exc
        if not parser.finished:
            raise invalid("La subida está incompleta.")
        files = form.getlist(field)
        if not files or any(not isinstance(item, UploadFile) for item in files):
            raise invalid(f"Incluye al menos una imagen en el campo '{field}'.")
        if any(isinstance(value, UploadFile) and key != field for key, value in form.multi_items()):
            raise invalid(f"Todos los archivos deben utilizar el campo '{field}'.")
        if any(item.size == 0 for item in files):
            raise invalid("No se aceptan archivos vacíos.")
        yield form, files
    finally:
        if form is not None:
            await form.close()
        # Cubre errores en callbacks, límites, formularios incompletos y cancelación.
        for temporary in parser._files_to_close_on_error:
            temporary.close()
