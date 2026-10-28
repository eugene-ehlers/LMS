"""Collection-campaign records.

A collection campaign is a temporary servicing overlay. It is not the
origination discount stored on the agreement at booking (LOCKED_DECISIONS §3
on this branch). The contractual rate, fees, instalment, and term stay on
the loan. The copies below are the values the campaign must not rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# Ledger fee buckets a collection campaign may reduce. Interest is a rate,
# not a fee. laybye_hold is not a fee.
FEE_TYPES = (
    "initiation",
    "service",
    "credit_insurance",
    "default_administration",
    "collection_costs",
    "additional_monthly",
)

# NCA section 104(2), as stated in the collection-campaign brief: written
# notice of at least five business days before the change takes effect.
# This is not a client election.
NOTICE_BUSINESS_DAYS = 5

# Decision 19: role names are descriptive. This branch's examples include
# lms.campaign.write for origination campaigns. Collection campaigns are a
# separate action. The exact name is not in the locked decisions; the gap
# is recorded in docs/collection-campaigns/gaps.md.
ROLE = "lms.collection_campaign.write"


@dataclass
class Campaign:
    campaign_id: str
    organisation_id: str
    start_date: date
    end_date: date | None
    rate_reduction: Decimal
    fee_reductions: dict[str, int]
    payment_holiday: bool
    notice_date: date
    notice_business_days: int
    created_by: str
    created_at: datetime


@dataclass
class RegisteredAccount:
    """Caller-supplied product and contractual fees. The ledger does not store them."""

    organisation_id: str
    loan_id: str
    product_code: str
    contractual_fees_cents: dict[str, int]


@dataclass
class Application:
    campaign_id: str
    organisation_id: str
    loan_id: str
    contractual_base_rate: Decimal
    contractual_discount_rate: Decimal
    contractual_periodic_rate: Decimal
    contractual_end: date
    contractual_instalments: tuple[tuple[date, int], ...]
    contractual_fees_cents: dict[str, int]
    skipped_due_dates: tuple[date, ...] = ()
    applied_by: str = ""
    applied_at: datetime | None = None
