"""NCR Form 39 readiness. Sourced facts only.

Regulation 64 sets who files and when. The current Schedule 1 artwork is
not transcribed (gap RX26). This module lists ledger and configuration
facts that can be read, and names the elements that are not stored.
It does not invent a zero for a missing element.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lms.ledger.service import Ledger
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.ncr import require_ncr_for_extract
from lms.regulatory.sacrra import OWED_BUCKETS
from lms_config.compliance import ComplianceStore

# Named by the task. Each one has no ledger or configuration column.
NOT_STORED = (
    "applications",
    "province",
    "gender",
    "income",
    "provisions",
    "write_offs",
    "age_analysis",
)


@dataclass(frozen=True)
class Form39Readiness:
    organisation_id: str
    period_start: date
    period_end: date
    ncr_registration_number: str | None
    legal_name: str | None
    gross_owed_cents: int
    gross_owed_cents_by_classification: dict[str, int]
    laybye_hold_cents: int
    agreements_disbursed_in_period: int
    cash_advanced_cents_disbursed_in_period: int
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
    """Read the book at ``period_end`` and the advances disbursed inside the period.

    Both dates are Johannesburg value dates (decision 1). The R15 million
    test in regulation 64 is not stored, so this function does not choose
    quarterly or annual filing (gap RX27).
    """
    if not organisation_id:
        raise RegulatoryError("organisation-unset", "The Form 39 extract needs an organisation id.")
    if period_end < period_start:
        raise RegulatoryError("date-range", "The Form 39 period ends before it starts.")
    parents = tuple(
        account
        for account in ledger.store.accounts_for(organisation_id)
        if account.instrument_kind == "loan" and account.disbursement_value_date <= period_end
    )
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
        owed = sum(ledger.bucket_balance(account, bucket, as_of=period_end) for bucket in OWED_BUCKETS)
        classification = account.snapshot.classification
        by_classification[classification] = by_classification.get(classification, 0) + owed
        gross += owed
        for child in ledger.store.accounts_for(organisation_id):
            if child.parent_loan_id == account.loan_id and child.instrument_kind == "laybye_hold":
                hold += ledger.bucket_balance(child, "laybye_hold", as_of=period_end)

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
        gross_owed_cents=gross,
        gross_owed_cents_by_classification=by_classification,
        laybye_hold_cents=hold,
        agreements_disbursed_in_period=len(disbursed),
        cash_advanced_cents_disbursed_in_period=sum(account.cash_advanced_cents for account in disbursed),
        not_stored=NOT_STORED,
    )
