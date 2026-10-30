"""Settlement failures. ``code`` is stable. The message is the reason a person can act on."""


class SettlementError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)
