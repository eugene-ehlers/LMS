"""Failures in the ledger. ``code`` is stable for callers."""


class LedgerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
