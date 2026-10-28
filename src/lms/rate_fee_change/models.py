"""A non-campaign rate or fee change.

The contractual rate, fees, instalment, and term stay on the loan. The
copies on ``AccountRateFee`` are the originals kept for disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# Ledger fee buckets this change may reduce. Interest is a rate.
# laybye_hold is not a fee.
FEE_TYPES = (
    "initiation",
    "service",
    "credit_insurance",
    "default_administration",
    "collection_costs",
    "additional_monthly",
)

# NCA section 104(2): written notice of at least five business days before
# the change takes effect. Section 2(5) counts that gap. This is not an election.
NOTICE_BUSINESS_DAYS = 5

# Decision 19 requires a descriptive role. It does not name this action.
# The gap is recorded in docs/rate-fee-change/gaps.md.
ROLE = "lms.rate_fee_change.write"

EVENT = "RATE_FEE_CHANGE"


@dataclass
class RateFeeChange:
    change_id: str
    organisation_id: str
    notice_date: date
    effective_date: date
    end_date: date | None
    periodic_rate: Decimal | None
    fees_cents: dict[str, int]
    fee_payment_frequency: str | None
    fee_payment_time: date | None
    notice_business_days: int
    created_by: str
    created_at: datetime
    ended_by: str | None = None
    ended_at: datetime | None = None


@dataclass
class AccountRateFee:
    change_id: str
    organisation_id: str
    loan_id: str
    contractual_periodic_rate: Decimal
    contractual_base_rate: Decimal
    contractual_discount_rate: Decimal
    contractual_fees_cents: dict[str, int]
    contractual_end: date
    contractual_instalments: tuple[tuple[date, int], ...]
    payment_frequency: str
    applied_by: str
    applied_at: datetime


@dataclass(frozen=True)
class Outcome:
    """Success carries a confirmation. Failure carries a specific reason."""

    ok: bool
    code: str
    message: str
    status: int = 200
    change_id: str | None = None
    loan_ids: tuple[str, ...] = ()
    notice_date: date | None = None
    effective_date: date | None = None
    end_date: date | None = None
    recognition_date: date | None = None


@dataclass(frozen=True)
class StatusReport:
    """The last audited apply, end, or refused accrual for an organisation."""

    found: bool
    outcome: str
    code: str
    message: str
    change_id: str | None = None
    action: str | None = None
    occurred_at: datetime | None = None
    loan_ids: tuple[str, ...] = ()
    recognition_date: date | None = None
