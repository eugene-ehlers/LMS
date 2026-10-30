"""Agreements held for a restructure.

Identity fields and, on the new agreement, the frozen elections and the
contractual terms are not rewritten after they are stored. Decision 16.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from lms.restructure.elections import FrozenElections


class FreezeError(Exception):
    """A concluded field was presented for rewrite."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} is frozen on the agreement and is not rewritten.")


_FROZEN = frozenset(
    {
        "agreement_id",
        "organisation_id",
        "person_id",
        "contractual_instalment_cents",
        "term_count",
        "payment_frequency",
        "contractual_periodic_rate_bps",
        "application_number",
        "frozen_full_name",
        "frozen_id_number",
        "frozen_service_address",
        "elections",
        "original_agreement_id",
        "client_consent",
        "consent_date",
        "recognised_at",
    }
)


@dataclass
class Agreement:
    agreement_id: str
    organisation_id: str
    person_id: str
    outstanding_balance_cents: int
    contractual_instalment_cents: int
    term_count: int
    payment_frequency: str
    contractual_periodic_rate_bps: int
    application_number: str
    frozen_full_name: str
    frozen_id_number: str
    frozen_service_address: str
    status: str = "active"
    elections: FrozenElections | None = None
    original_agreement_id: str | None = None
    restructured_to_agreement_id: str | None = None
    client_consent: bool | None = None
    consent_date: date | None = None
    recognised_at: datetime | None = None

    def __setattr__(self, name: str, value: object) -> None:
        if name in _FROZEN and name in self.__dict__:
            raise FreezeError(name)
        object.__setattr__(self, name, value)
