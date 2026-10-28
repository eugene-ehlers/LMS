"""Refusals for a section 104 rate or fee change. A refusal stores no change."""

from __future__ import annotations


class RateFeeChangeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 422,
        loan_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.loan_ids = loan_ids
        self.audited = False
