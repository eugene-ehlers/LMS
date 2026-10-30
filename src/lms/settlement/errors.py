"""Settlement failures. ``code`` is stable. The message is the reason a person can act on.

``extra`` carries fields a re-advance failure already returns. An early-settlement
failure leaves it empty.
"""


class SettlementError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422, extra: dict | None = None) -> None:
        self.code = code
        self.status = status
        self.extra = extra or {}
        super().__init__(message)
