"""Staff-command failures. ``code`` is stable. Nothing here chooses a locked value."""


class StaffError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)
