"""Settlement re-advance failures. ``code`` is stable. Nothing here chooses a locked value."""


class SettlementError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422, extra: dict | None = None) -> None:
        self.code = code
        self.status = status
        self.extra = extra or {}
        super().__init__(message)
