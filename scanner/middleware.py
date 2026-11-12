"""Límites previos al parser, incluidas peticiones chunked sin Content-Length."""

from starlette.responses import JSONResponse

from scanner.errors import ScanError, too_large


def error_response(error):
    body = {"code": error.code, "message": error.message}
    if error.message_key is not None:
        body["message_key"] = error.message_key
    if error.params is not None:
        body["params"] = error.params
    return JSONResponse({"error": body}, status_code=error.status)


class ResourceGuard:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def secure_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message.setdefault("headers", []).extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                    ]
                )
            await send(message)

        limited = scope["method"] == "POST" and scope["path"].startswith("/api/")
        if not limited:
            return await self.app(scope, receive, secure_send)
        # El incremento ocurre sin await: adquisición atómica dentro del event loop único.
        if self.active >= self.settings.max_concurrency:
            response = error_response(
                ScanError(503, "busy", "El escáner está ocupado. Reintenta en unos segundos.", "errors.busy")
            )
            response.headers["Retry-After"] = "2"
            return await response(scope, receive, secure_send)
        self.active += 1
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.settings.max_request_bytes:
                    raise too_large("La petición supera el tamaño máximo permitido.", "errors.requestSize")
            return message

        try:
            headers = dict(scope["headers"])
            if b"content-length" in headers:
                try:
                    length = int(headers[b"content-length"])
                    if length < 0:
                        raise ValueError
                except ValueError:
                    raise ScanError(
                        422, "invalid_length", "Content-Length no válido.", "errors.contentLength"
                    ) from None
                if length > self.settings.max_request_bytes:
                    raise too_large("La petición supera el tamaño máximo permitido.", "errors.requestSize")
            await self.app(scope, limited_receive, secure_send)
        except ScanError as error:
            if started:
                raise
            await error_response(error)(scope, receive, secure_send)
        finally:
            self.active -= 1
