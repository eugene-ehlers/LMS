"""Failures in regulatory extracts. ``code`` is stable for callers."""


class RegulatoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
