"""SACRRA mapped data. No submission file.

The monthly L700v2 layout is described in the design note. Mandatory-field
rules are not locked, so ``file_bytes`` stays empty. Status codes, months
in arrears, and account-type codes stay unset.

Balances are ``Ledger.bucket_balance`` on the caller-supplied Johannesburg
value date (decision 1). Unbilled interest is a memo until ``bill_interest``
(decision 6). A linked lay-by is one parent row, and the hold is not
subtracted from principal (decision 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lms.ledger.models import BUCKETS
from lms.ledger.service import Ledger
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.ncr import require_ncr_for_extract
from lms_config.compliance import ComplianceStore

# Debit-normal buckets. ``laybye_hold`` is credit-normal and is reported beside them.
OWED_BUCKETS = tuple(bucket for bucket in BUCKETS if bucket != "laybye_hold")


@dataclass(frozen=True)
class SacrraRow:
    """One parent agreement. Prescribed codes that are not locked are None."""

    organisation_id: str
    loan_id: str
    person_id: str
    frozen_full_name: str
    frozen_id_number: str
    frozen_service_address: str
    classification: str
    disbursement_value_date: date
    as_of: date
    bucket_cents: dict[str, int]
    principal_cents: int
    laybye_hold_cents: int
    status_code: None = None
    months_in_arrears: None = None
    account_type_code: None = None


@dataclass(frozen=True)
class SacrraExtract:
    """Mapped rows for one organisation. ``file_bytes`` is always None."""

    organisation_id: str
    as_of: date
    ncr_registration_number: str | None
    rows: tuple[SacrraRow, ...]
    file_bytes: None = None


def build_sacrra_extract(
    ledger: Ledger,
    compliance: ComplianceStore,
    *,
    organisation_id: str,
    as_of: date,
    pure_hosting: bool | None,
) -> SacrraExtract:
    """Map parent loans visible on ``as_of``. Do not post and do not emit a file.

    ``as_of`` is a Johannesburg value date supplied by the caller (decision 1).
    The month-end versus billing-date choice is not locked, so this function
    does not choose one.
    """
    if not organisation_id:
        raise RegulatoryError("organisation-unset", "The SACRRA extract needs an organisation id.")
    parents = tuple(
        account
        for account in ledger.store.accounts_for(organisation_id)
        if account.instrument_kind == "loan" and account.disbursement_value_date <= as_of
    )
    number = require_ncr_for_extract(
        compliance,
        organisation_id=organisation_id,
        classifications=tuple(account.snapshot.classification for account in parents),
        pure_hosting=pure_hosting,
    )
    rows = tuple(_row(ledger, account, as_of) for account in parents)
    return SacrraExtract(
        organisation_id=organisation_id,
        as_of=as_of,
        ncr_registration_number=number,
        rows=rows,
        file_bytes=None,
    )


def _row(ledger: Ledger, account, as_of: date) -> SacrraRow:
    buckets = {
        bucket: ledger.bucket_balance(account, bucket, as_of=as_of) for bucket in OWED_BUCKETS
    }
    hold = 0
    for child in ledger.store.accounts_for(account.organisation_id):
        if child.parent_loan_id == account.loan_id and child.instrument_kind == "laybye_hold":
            # Decision 4. The hold is the child's bucket. It is not a second row
            # and it is not deducted from principal.
            hold += ledger.bucket_balance(child, "laybye_hold", as_of=as_of)
    buckets["laybye_hold"] = hold
    return SacrraRow(
        organisation_id=account.organisation_id,
        loan_id=account.loan_id,
        person_id=account.person_id,
        frozen_full_name=account.frozen_full_name,
        frozen_id_number=account.frozen_id_number,
        frozen_service_address=account.frozen_service_address,
        classification=account.snapshot.classification,
        disbursement_value_date=account.disbursement_value_date,
        as_of=as_of,
        bucket_cents=buckets,
        principal_cents=buckets["principal"],
        laybye_hold_cents=hold,
    )
