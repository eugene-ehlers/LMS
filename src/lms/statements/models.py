"""Stored statements, enquiries, and settlement quotes.

Figures are copied at issue. Nothing here recalculates a balance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class TransactionView:
    loan_id: str
    value_date: date
    recognition_sequence: int
    kind: str
    bucket: str | None
    debit_cents: int
    credit_cents: int
    memo_rands: Decimal | None
    description: str


@dataclass(frozen=True)
class LoanSection:
    """One loan on the client statement. Balances are per bucket.

    ``opening`` equals the previous statement's ``closing`` for this loan
    when a previous statement exists (locked decision 12 and section 109).
    Principal, billed interest, each fee bucket, and the lay-by hold are
    separate keys. The hold is not subtracted from principal (decision 4).
    """

    loan_id: str
    instrument_kind: str
    parent_loan_id: str | None
    frozen_full_name: str
    frozen_id_number: str
    frozen_service_address: str
    payment_frequency: str
    principal_debt_cents: int
    opening: dict[str, int]
    closing: dict[str, int]
    opening_source: str
    base_rate: Decimal
    discount_rate: Decimal
    discount_fallen_away: bool
    periodic_rate_in_force: Decimal | None
    nominal_annual_on_base: Decimal | None
    nominal_annual_on_effective: Decimal | None
    # Regulation 35(e)(ii) asks for one annual rate. Decision 17 does not say
    # whether a campaign multiplies the base or the net. The cell stays empty.
    annual_rate_cell: None
    instalment_cents: int | None
    instalment_due_on: date | None
    payments_received_cents: int
    fees_levied_cents: int
    interest_billed_cents: int
    interest_memo_rands: Decimal
    insurance_levied_cents: int
    collection_levied_cents: int
    default_administration_levied_cents: int
    # Regulation 35(f)(vii). No ledger bucket. Not folded into collection costs.
    legal_fees_cents: None
    # Decision 8 names arrears and does not define the cents.
    arrears_cents: None
    # Unpaid slices and charges with due_on before the statement date. Not a total.
    overdue: tuple[tuple[str, date, int], ...]
    open_default_episode: bool
    transactions: tuple[TransactionView, ...]


@dataclass(frozen=True)
class StoredStatement:
    statement_id: str
    organisation_id: str
    person_id: str
    period_start: date
    period_end: date
    statement_date: date
    legal_name: str
    ncr_registration_number: str
    trading_name: str
    physical_address: str
    postal_address: str
    telephone: str
    bank_name: str
    bank_account_number: str
    branch_code: str
    payment_reference: str
    loans: tuple[LoanSection, ...]
    pdf_sha256: str
    pdf_stub: bytes


@dataclass(frozen=True)
class AmountOwing:
    """Section 110 answer. Not a periodic statement."""

    organisation_id: str
    person_id: str
    loan_id: str
    request_on: date
    components: dict[str, int]
    overdue: tuple[tuple[str, date, int], ...]
    payable: tuple[tuple[str, date, int], ...]
    transactions: tuple[TransactionView, ...]
    deliver_by: date


@dataclass(frozen=True)
class StoredQuote:
    """Section 113 quote. Early-termination cents are the engine's figure."""

    agreement_id: str
    organisation_id: str
    person_id: str
    as_of: date
    delivered_on: date
    valid_until: date
    deliver_by: date
    principal_cents: int
    interest_cents: int
    fee_cents: int
    early_termination_cents: int
    total_cents: int
    agreement_size: str
    components: tuple[tuple[str, int], ...]
