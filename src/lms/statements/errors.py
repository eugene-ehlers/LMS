"""Statement and document failures. ``code`` is stable."""


class DocumentsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
