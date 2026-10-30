"""NCR Form 39 readiness. Sourced facts only.

Regulation 64 sets the calendar: quarterly when annual disbursements exceed
R15 million, otherwise annually by 15 February. The R15 million test is not
stored, so the caller supplies the Johannesburg period. This module does not
choose quarterly or annual filing.

Gross book is the billed ledger buckets at the period end. Unbilled interest
stays out until it is billed. The lay-by hold is not subtracted from principal.
Applications, province, gender, income, provisions, write-offs, and age
analysis are not stored as Form 39 cells. Those cells stay empty. A write-off
journal on the ledger is not mapped onto the write-off cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lms.ledger.service import Ledger
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.ncr import require_ncr_for_extract
from lms.regulatory.sacrra import laybye_hold_cents, owed_cents, parent_loans
from lms_config.compliance import ComplianceStore

# Named by the task. Each one has no Form 39 column on the LMS.
NOT_STORED = (
    "applications",
    "province",
    "gender",
    "income",
    "provisions",
    "write_offs",
    "age_analysis",
)

REGULATION_64 = (
    "Regulation 64: quarterly when annual disbursements exceed R15 million, "
    "otherwise annually by 15 February. The R15 million test is not stored. "
    "The caller supplies the period."
)


@dataclass(frozen=True)
class Form39Readiness:
    organisation_id: str
    period_start: date
    period_end: date
    ncr_registration_number: str | None
    legal_name: str | None
    gross_book_cents: int
    gross_book_cents_by_classification: dict[str, int]
    laybye_hold_cents: int
    agreements_disbursed_in_period: int
    cash_advanced_cents_disbursed_in_period: int
    filing_rule: str = REGULATION_64
    applications: None = None
    province: None = None
    gender: None = None
    income: None = None
    provisions: None = None
    write_offs: None = None
    age_analysis: None = None
    not_stored: tuple[str, ...] = NOT_STORED


def build_form39_readiness(
    ledger: Ledger,
    compliance: ComplianceStore,
    *,
    organisation_id: str,
    period_start: date,
    period_end: date,
    pure_hosting: bool | None,
) -> Form39Readiness:
    """Read the billed book at ``period_end``. Do not choose the filing calendar.

    Both dates are Johannesburg value dates (decision 1). Cash advanced in the
    period is the stored advance. It is not a ruling on which Form 39 cell
    that figure fills.
    """
    if not organisation_id or not str(organisation_id).strip():
        raise RegulatoryError("organisation-unset", "The Form 39 extract needs an organisation id.")
    if type(period_start) is not date or type(period_end) is not date:
        raise RegulatoryError("date-range", "The Form 39 period must be Johannesburg calendar dates.")
    if period_end < period_start:
        raise RegulatoryError("date-range", "The Form 39 period ends before it starts.")
    parents = parent_loans(ledger, organisation_id, period_end)
    number = require_ncr_for_extract(
        compliance,
        organisation_id=organisation_id,
        classifications=tuple(account.snapshot.classification for account in parents),
        pure_hosting=pure_hosting,
    )
    record = compliance.find(organisation_id)
    legal_name = record.legal_name.strip() if record is not None and record.legal_name.strip() else None

    by_classification: dict[str, int] = {}
    gross = 0
    hold = 0
    for account in parents:
        buckets = owed_cents(ledger, account, period_end)
        owed = sum(buckets.values())
        classification = account.snapshot.classification
        by_classification[classification] = by_classification.get(classification, 0) + owed
        gross += owed
        hold += laybye_hold_cents(ledger, account, period_end)

    disbursed = tuple(
        account
        for account in parents
        if period_start <= account.disbursement_value_date <= period_end
    )
    return Form39Readiness(
        organisation_id=organisation_id,
        period_start=period_start,
        period_end=period_end,
        ncr_registration_number=number,
        legal_name=legal_name,
        gross_book_cents=gross,
        gross_book_cents_by_classification=by_classification,
        laybye_hold_cents=hold,
        agreements_disbursed_in_period=len(disbursed),
        cash_advanced_cents_disbursed_in_period=sum(account.cash_advanced_cents for account in disbursed),
    )
