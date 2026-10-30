"""Failures in the Laybye layer. ``code`` is stable for callers."""


class LaybyeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
