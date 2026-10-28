"""Decision-engine port.

The LMS sends an application and stores the approval it gets back. It does not
re-decide concurrent, subsequent, settled-and-readvanced, or restructure rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from lms.errors import ContractError
from lms.validation import require_cents, require_non_negative_int, require_positive_int, require_text


class PaymentFrequency(StrEnum):
    """Frequencies locked for the LMS. The wire value is the enum value."""

    WEEKLY = "weekly"
    FORTNIGHTLY = "fortnightly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    BI_ANNUAL = "bi-annual"
    ANNUAL = "annual"


class ShortTermRateBand(StrEnum):
    """The 5 % / 3 % short-term distinction, when the decision engine supplies it.

    This flag is not the contractual rate. The rate is a separate field.
    """

    FIVE_PERCENT = "five_percent"
    THREE_PERCENT = "three_percent"


def require_payment_frequency(value: object) -> PaymentFrequency:
    if isinstance(value, PaymentFrequency):
        return value
    if isinstance(value, str):
        try:
            return PaymentFrequency(value)
        except ValueError:
            pass
    raise ContractError(
        "payment_frequency must be one of weekly, fortnightly, monthly, "
        "quarterly, bi-annual, annual"
    )


def require_short_term_rate_band(value: object) -> ShortTermRateBand | None:
    if value is None:
        return None
    if isinstance(value, ShortTermRateBand):
        return value
    if isinstance(value, str):
        try:
            return ShortTermRateBand(value)
        except ValueError:
            pass
    raise ContractError(
        "short_term_rate_band must be five_percent, three_percent, or absent"
    )


@dataclass(frozen=True)
class ConsumerIdentity:
    """Identity the application carries. Opaque ``person_id`` plus the name and ID number."""

    person_id: str
    name: str
    id_number: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_id", require_text(self.person_id, "person_id"))
        object.__setattr__(self, "name", require_text(self.name, "name"))
        object.__setattr__(self, "id_number", require_text(self.id_number, "id_number"))


@dataclass(frozen=True)
class Application:
    """What the LMS submits. Amounts are integer cents."""

    consumer: ConsumerIdentity
    requested_amount_cents: int
    product_type: str
    term_count: int
    payment_frequency: PaymentFrequency

    def __post_init__(self) -> None:
        if not isinstance(self.consumer, ConsumerIdentity):
            raise ContractError("consumer must be a ConsumerIdentity")
        object.__setattr__(
            self,
            "requested_amount_cents",
            require_cents(self.requested_amount_cents, "requested_amount_cents"),
        )
        object.__setattr__(self, "product_type", require_text(self.product_type, "product_type"))
        object.__setattr__(self, "term_count", require_positive_int(self.term_count, "term_count"))
        object.__setattr__(
            self,
            "payment_frequency",
            require_payment_frequency(self.payment_frequency),
        )


@dataclass(frozen=True)
class Approval:
    """What the LMS stores. It does not recalculate these fields."""

    application_number: str
    contractual_periodic_rate_bps: int
    term_count: int
    payment_frequency: PaymentFrequency
    instalment_cents: int
    credit_life_premium_cents: int
    short_term_rate_band: ShortTermRateBand | None
    kind: Literal["approval"] = "approval"

    def __post_init__(self) -> None:
        if self.kind != "approval":
            raise ContractError("approval kind is fixed")
        object.__setattr__(
            self, "application_number", require_text(self.application_number, "application_number")
        )
        object.__setattr__(
            self,
            "contractual_periodic_rate_bps",
            require_non_negative_int(
                self.contractual_periodic_rate_bps, "contractual_periodic_rate_bps"
            ),
        )
        object.__setattr__(self, "term_count", require_positive_int(self.term_count, "term_count"))
        object.__setattr__(
            self, "payment_frequency", require_payment_frequency(self.payment_frequency)
        )
        object.__setattr__(
            self, "instalment_cents", require_cents(self.instalment_cents, "instalment_cents")
        )
        object.__setattr__(
            self,
            "credit_life_premium_cents",
            require_cents(self.credit_life_premium_cents, "credit_life_premium_cents"),
        )
        object.__setattr__(
            self,
            "short_term_rate_band",
            require_short_term_rate_band(self.short_term_rate_band),
        )


@dataclass(frozen=True)
class Decline:
    """A fixed refusal. No rate, instalment, premium, or short-term flag is supplied."""

    application_number: str
    kind: Literal["decline"] = "decline"

    def __post_init__(self) -> None:
        if self.kind != "decline":
            raise ContractError("decline kind is fixed")
        object.__setattr__(
            self, "application_number", require_text(self.application_number, "application_number")
        )


Decision = Approval | Decline


@runtime_checkable
class DecisionEngine(Protocol):
    """LMS call site: ``engine.decide(application)``."""

    def decide(self, application: Application) -> Decision:
        """Return an approval or a decline for this application."""
