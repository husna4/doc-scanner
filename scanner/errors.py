class ScanError(Exception):
    def __init__(
        self, status: int, code: str, message: str, message_key: str | None = None, params: dict | None = None
    ):
        self.status = status
        self.code = code
        self.message = message
        self.message_key = message_key
        self.params = params
        super().__init__(message)


def too_large(message: str, message_key: str | None = None, params: dict | None = None):
    return ScanError(413, "limit_exceeded", message, message_key, params)


def invalid(message: str, message_key: str | None = None, params: dict | None = None):
    return ScanError(422, "invalid_image_or_parameters", message, message_key, params)
