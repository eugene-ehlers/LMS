"""Port for the daily calculation steps.

The batch calls these steps. It does not decide rates, day count, capitalisation
amounts, or whether an account is in default. A missing or failed step is
reported. It is not treated as success.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class AccountStepError(Exception):
    """One account failed one step, with a reason an operator can act on."""

    def __init__(self, step: str, reason: str) -> None:
        self.step = step
        self.reason = reason
        super().__init__(reason)


class DailyCalculation(Protocol):
    def accrue(
        self,
        *,
        organisation_id: str,
        account_id: str,
        recognition_at: datetime,
    ) -> None:
        """Ledger.accrue_day for one account at the recognition instant."""

    def capitalise(
        self,
        *,
        organisation_id: str,
        account_id: str,
        recognition_at: datetime,
    ) -> None:
        """Capitalise due interest and service fees for one account."""

    def default_check(
        self,
        *,
        organisation_id: str,
        account_id: str,
        recognition_at: datetime,
    ) -> None:
        """Morning default check for one account."""
