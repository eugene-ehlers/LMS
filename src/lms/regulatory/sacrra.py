"""SACRRA monthly layout. No submission file.

Regulation 19(13) requires credit information in the form the NCR prescribes.
The field list below is the 56-field monthly L700v2 layout in the SACRRA
overview of that guideline. Mandatory-field rules, status codes, months in
arrears, account-type codes, and the N 9 amount scale are not locked, so
every layout value stays empty and ``render_l700_file`` refuses to emit a file.

Identity on the row is the name, ID number, and service address frozen at
booking (decision 16). Those strings are not split into the L700 columns.
Balances are ``Ledger.bucket_balance`` on the caller-supplied Johannesburg
value date (decision 1). Unbilled interest is a memo until ``bill_interest``
(decision 6). A linked lay-by is one parent row, and the hold is not
subtracted from principal (decision 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lms.ledger.models import BUCKETS, LoanAccount
from lms.ledger.service import Ledger
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.ncr import require_ncr_for_extract
from lms_config.compliance import ComplianceStore

# Debit-normal buckets. ``laybye_hold`` is credit-normal and is reported beside them.
OWED_BUCKETS = tuple(bucket for bucket in BUCKETS if bucket != "laybye_hold")

# L700 amount columns. The overview's N 9 scale is not locked (gap RX50).
AMOUNT_FIELD_NUMBERS = frozenset({32, 33, 35, 36})
# Prescribed codes the task leaves unset.
STATUS_FIELD_NUMBER = 38
MONTHS_IN_ARREARS_FIELD_NUMBER = 37
ACCOUNT_TYPE_FIELD_NUMBER = 28


@dataclass(frozen=True)
class L700Field:
    """One column of the monthly layout. ``value`` stays None until a rule is locked."""

    number: int
    name: str
    start: int
    end: int
    format: str
    value: None = None


# Positions are the overview's monthly example, as recorded in the Layer 1 draft.
# Widths are contiguous from 1 to 700. Import fails if that chain breaks.
_LAYOUT_ROWS = (
    (1, "DATA", 1, 1, "A 1"),
    (2, "SA ID NUMBER", 2, 14, "N 13"),
    (3, "NON-SA ID NUMBER", 15, 30, "A 16"),
    (4, "GENDER", 31, 31, "A 1"),
    (5, "DATE OF BIRTH", 32, 39, "N 8"),
    (6, "BRANCH CODE", 40, 47, "A 8"),
    (7, "ACCOUNT NO.", 48, 72, "A 25"),
    (8, "SUB-ACCOUNT NO.", 73, 76, "A 4"),
    (9, "SURNAME", 77, 101, "A 25"),
    (10, "TITLE", 102, 106, "A 5"),
    (11, "FORENAME OR INITIAL 1", 107, 120, "A 14"),
    (12, "FORENAME OR INITIAL 2", 121, 134, "A 14"),
    (13, "FORENAME OR INITIAL 3", 135, 148, "A 14"),
    (14, "RESIDENTIAL ADDRESS LINE 1", 149, 173, "A 25"),
    (15, "RESIDENTIAL ADDRESS LINE 2", 174, 198, "A 25"),
    (16, "RESIDENTIAL ADDRESS LINE 3", 199, 223, "A 25"),
    (17, "RESIDENTIAL ADDRESS LINE 4", 224, 248, "A 25"),
    (18, "POSTAL CODE OF RESIDENTIAL ADDRESS", 249, 254, "A 6"),
    (19, "OWNER / TENANT", 255, 255, "A 1"),
    (20, "POSTAL ADDRESS LINE 1", 256, 280, "A 25"),
    (21, "POSTAL ADDRESS LINE 2", 281, 305, "A 25"),
    (22, "POSTAL ADDRESS LINE 3", 306, 330, "A 25"),
    (23, "POSTAL ADDRESS LINE 4", 331, 355, "A 25"),
    (24, "POSTAL CODE OF POSTAL ADDRESS", 356, 361, "A 6"),
    (25, "OWNERSHIP TYPE", 362, 363, "A 2"),
    (26, "LOAN REASON CODE", 364, 365, "A 2"),
    (27, "PAYMENT TYPE", 366, 367, "A 2"),
    (28, "TYPE OF ACCOUNT", 368, 369, "A 2"),
    (29, "DATE ACCOUNT OPENED", 370, 377, "N 8"),
    (30, "DEFERRED PAYMENT DATE", 378, 385, "N 8"),
    (31, "DATE OF LAST PAYMENT", 386, 393, "N 8"),
    (32, "OPENING BALANCE / CREDIT LIMIT", 394, 402, "N 9"),
    (33, "CURRENT BALANCE", 403, 411, "N 9"),
    (34, "CURRENT BALANCE INDICATOR", 412, 412, "A 1"),
    (35, "AMOUNT OVERDUE", 413, 421, "N 9"),
    (36, "INSTALMENT AMOUNT", 422, 430, "N 9"),
    (37, "MONTHS IN ARREARS", 431, 432, "N 2"),
    (38, "STATUS CODE", 433, 434, "A 2"),
    (39, "REPAYMENT FREQUENCY", 435, 436, "N 2"),
    (40, "TERMS", 437, 440, "N 4"),
    (41, "STATUS DATE", 441, 448, "N 8"),
    (42, "OLD SUPPLIER BRANCH CODE", 449, 456, "A 8"),
    (43, "OLD ACCOUNT NUMBER", 457, 481, "A 25"),
    (44, "OLD SUB-ACCOUNT NUMBER", 482, 485, "A 4"),
    (45, "OLD SUPPLIER REFERENCE NUMBER", 486, 495, "A 10"),
    (46, "HOME TELEPHONE", 496, 511, "A 16"),
    (47, "CELLULAR TELEPHONE", 512, 527, "A 16"),
    (48, "WORK TELEPHONE", 528, 543, "A 16"),
    (49, "EMPLOYER DETAIL", 544, 603, "A 60"),
    (50, "INCOME", 604, 612, "N 9"),
    (51, "INCOME FREQUENCY", 613, 613, "A 1"),
    (52, "OCCUPATION", 614, 633, "A 20"),
    (53, "THIRD PARTY NAME", 634, 693, "A 60"),
    (54, "ACCOUNT SOLD TO THIRD PARTY", 694, 695, "N 2"),
    (55, "NO OF PARTICIPANTS IN JOINT LOAN", 696, 698, "N 3"),
    (56, "FILLER", 699, 700, "A 2"),
)


def _monthly_layout() -> tuple[L700Field, ...]:
    fields = tuple(L700Field(*row) for row in _LAYOUT_ROWS)
    if len(fields) != 56:
        raise RegulatoryError("layout-incomplete", "The monthly L700 layout must have 56 fields.")
    if fields[0].start != 1 or fields[-1].end != 700:
        raise RegulatoryError("layout-incomplete", "The monthly L700 layout must cover positions 1 to 700.")
    previous: L700Field | None = None
    for field in fields:
        width = int(field.format.split()[1])
        if field.end - field.start + 1 != width:
            raise RegulatoryError("layout-incomplete", f"Field {field.number} width does not match its format.")
        if previous is not None and (field.number != previous.number + 1 or field.start != previous.end + 1):
            raise RegulatoryError("layout-incomplete", f"Field {field.number} is not contiguous.")
        if field.value is not None:
            raise RegulatoryError("layout-incomplete", f"Field {field.number} must stay empty.")
        previous = field
    return fields


L700_MONTHLY_FIELDS = _monthly_layout()


@dataclass(frozen=True)
class SacrraRow:
    """One parent agreement. Prescribed codes and the N 9 scale stay None."""

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
    amount_scale: None = None


@dataclass(frozen=True)
class SacrraExtract:
    """Mapped rows for one organisation. ``file_bytes`` is always None."""

    organisation_id: str
    as_of: date
    ncr_registration_number: str | None
    rows: tuple[SacrraRow, ...]
    layout: tuple[L700Field, ...] = L700_MONTHLY_FIELDS
    file_bytes: None = None


def render_l700_file(extract: SacrraExtract) -> None:
    """Refuse a submission file. Mandatory-field rules are not locked."""

    del extract
    raise RegulatoryError(
        "mandatory-fields-unlocked",
        "No L700 file is emitted until the mandatory-field rules are locked.",
    )


def parent_loans(ledger: Ledger, organisation_id: str, as_of: date) -> tuple[LoanAccount, ...]:
    """Parents already disbursed on or before ``as_of``. A prepared loan is not opened."""

    parents: list[LoanAccount] = []
    for account in ledger.store.accounts_for(organisation_id):
        if account.instrument_kind != "loan":
            continue
        opened = account.disbursement_value_date
        if opened is None or opened > as_of:
            continue
        parents.append(account)
    return tuple(parents)


def laybye_hold_cents(ledger: Ledger, account: LoanAccount, as_of: date) -> int:
    """Decision 4. The hold is the child's bucket. It is not a second row."""

    hold = 0
    for child in ledger.store.accounts_for(account.organisation_id):
        if child.parent_loan_id == account.loan_id and child.instrument_kind == "laybye_hold":
            hold += ledger.bucket_balance(child, "laybye_hold", as_of=as_of)
    return hold


def owed_cents(ledger: Ledger, account: LoanAccount, as_of: date) -> dict[str, int]:
    """Posted debit-normal buckets. Memos are not entries, so unbilled interest is zero."""

    return {bucket: ledger.bucket_balance(account, bucket, as_of=as_of) for bucket in OWED_BUCKETS}


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
    if not organisation_id or not str(organisation_id).strip():
        raise RegulatoryError("organisation-unset", "The SACRRA extract needs an organisation id.")
    if type(as_of) is not date:
        raise RegulatoryError("date-range", "The SACRRA as-of value must be a Johannesburg calendar date.")
    parents = parent_loans(ledger, organisation_id, as_of)
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
        layout=L700_MONTHLY_FIELDS,
        file_bytes=None,
    )


def _row(ledger: Ledger, account: LoanAccount, as_of: date) -> SacrraRow:
    buckets = owed_cents(ledger, account, as_of)
    hold = laybye_hold_cents(ledger, account, as_of)
    buckets["laybye_hold"] = hold
    opened = account.disbursement_value_date
    if not isinstance(opened, date):
        raise RegulatoryError("date-range", "A SACRRA parent needs a disbursement value date.")
    return SacrraRow(
        organisation_id=account.organisation_id,
        loan_id=account.loan_id,
        person_id=account.person_id,
        frozen_full_name=account.frozen_full_name,
        frozen_id_number=account.frozen_id_number,
        frozen_service_address=account.frozen_service_address,
        classification=account.snapshot.classification,
        disbursement_value_date=opened,
        as_of=as_of,
        bucket_cents=buckets,
        principal_cents=buckets["principal"],
        laybye_hold_cents=hold,
    )
