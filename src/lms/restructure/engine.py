"""Decision-engine port for a restructure.

The engine supplies the new rate, term, and instalment. The LMS stores that
reply. It does not re-decide concurrent, subsequent, settled-and-readvanced,
or restructure rules. Decision 13.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RestructureFacts:
    """Facts already stored. Not a proposed price."""

    organisation_id: str
    agreement_id: str
    person_id: str
    outstanding_balance_cents: int
    contractual_instalment_cents: int
    term_count: int
    payment_frequency: str
    contractual_periodic_rate_bps: int


@dataclass(frozen=True)
class SuppliedTerms:
    """The reply the LMS stores. Amounts are integer cents. The rate is the integer supplied."""

    contractual_periodic_rate_bps: int
    term_count: int
    payment_frequency: str
    instalment_cents: int
    application_number: str


@dataclass(frozen=True)
class Refusal:
    """A reply the LMS cannot store as terms.

    ``code`` is ``timeout``, ``ambiguous``, ``unavailable``, ``rejected``,
    or ``incomplete``.
    """

    code: str
    detail: str = ""


class EngineError(Exception):
    """The engine call did not return terms. ``code`` matches :class:`Refusal`."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@runtime_checkable
class DecisionEngine(Protocol):
    def supply(self, facts: RestructureFacts) -> SuppliedTerms | Refusal:
        """Return the new rate, term, and instalment, or a refusal."""
