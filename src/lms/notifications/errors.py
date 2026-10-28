"""Failures for the statement-ready push. ``code`` is stable. Nothing is sent."""


class NotificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
