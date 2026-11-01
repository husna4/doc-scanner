class ScanError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def too_large(message: str):
    return ScanError(413, "limit_exceeded", message)


def invalid(message: str):
    return ScanError(422, "invalid_image_or_parameters", message)
