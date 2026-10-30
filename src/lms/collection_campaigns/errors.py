"""Errors for collection campaigns. A refused command posts nothing."""

from __future__ import annotations


class CollectionCampaignError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
