"""Account and ledger rows.

Balances are not stored. A bucket balance is the sum of the entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from lms.ledger.errors import LedgerError
from lms_config.locked import ResolvedCreditSettings


BUCKETS = (
    "principal",
    "interest",
    "initiation",
    "service",
    "credit_insurance",
    "default_administration",
    "collection_costs",
    "additional_monthly",
    "laybye_hold",
)

FREQUENCIES = (
    "weekly",
    "fortnightly",
    "monthly",
    "quarterly",
    "bi_annual",
    "annual",
)

_FROZEN_ACCOUNT_FIELDS = frozenset(
    {
        "organisation_id",
        "loan_id",
        "person_id",
        "parent_loan_id",
        "instrument_kind",
        "frozen_full_name",
        "frozen_id_number",
        "frozen_service_address",
        "snapshot",
        "payment_frequency",
        "disbursement_value_date",
        "quoted_disbursement",
        "contractual_end",
        "cash_advanced_cents",
    }
)


@dataclass(frozen=True)
class ElectionSnapshot:
    """Elections copied at booking. A later organisation edit does not rewrite them."""

    leniency_days: int
    full_payment_threshold_percent: Decimal
    interest_on_deferred_initiation: str
    repo_rate_fall: str
    day_count_code: str | None
    base_rate: Decimal
    discount_rate: Decimal
    vat_on_rand_maxima: str
    late_disbursement: str
    partial_prepayment: str
    initiation_capitalised: bool
    payment_frequency: str
    classification: str

    @classmethod
    def from_resolved(
        cls,
        resolved: ResolvedCreditSettings,
        *,
        initiation_capitalised: bool,
        payment_frequency: str,
        classification: str,
    ) -> ElectionSnapshot:
        return cls(
            leniency_days=resolved.leniency_days,
            full_payment_threshold_percent=resolved.full_payment_threshold_percent,
            interest_on_deferred_initiation=resolved.interest_on_deferred_initiation,
            repo_rate_fall=resolved.repo_rate_fall,
            day_count_code=resolved.day_count_code,
            base_rate=resolved.base_rate,
            discount_rate=resolved.discount_rate,
            vat_on_rand_maxima=resolved.vat_on_rand_maxima,
            late_disbursement=resolved.late_disbursement,
            partial_prepayment=resolved.partial_prepayment,
            initiation_capitalised=initiation_capitalised,
            payment_frequency=payment_frequency,
            classification=classification,
        )


@dataclass(frozen=True)
class ScheduleVersion:
    version_no: int
    effective_value_date: date
    reason: str
    late_disbursement: str | None
    lines: tuple[tuple[date, int], ...]


@dataclass
class Slice:
    due_on: date
    amount_cents: int
    remaining_cents: int
    sequence: int


@dataclass
class DueCharge:
    charge_id: str
    bucket: str
    due_on: date
    remaining_cents: int
    sequence: int
    levied_on: date
    ex_vat_cents: int = 0
    vat_cents: int = 0


@dataclass
class Episode:
    episode_no: int
    started_on: date
    ceiling_cents: int
    accrued_cents: int = 0
    closed_on: date | None = None


@dataclass
class LoanAccount:
    organisation_id: str
    loan_id: str
    person_id: str
    parent_loan_id: str | None
    instrument_kind: str
    frozen_full_name: str
    frozen_id_number: str
    frozen_service_address: str
    snapshot: ElectionSnapshot
    payment_frequency: str
    disbursement_value_date: date | None
    quoted_disbursement: date | None
    contractual_end: date
    cash_advanced_cents: int
    capitalised_initiation_cents: int = 0
    slices: list[Slice] = field(default_factory=list)
    charges: list[DueCharge] = field(default_factory=list)
    episodes: list[Episode] = field(default_factory=list)
    discount_fallen_away: bool = False
    service_months: set[tuple[int, int]] = field(default_factory=set)
    schedule_versions: list[ScheduleVersion] = field(default_factory=list)
    next_charge_sequence: int = 1

    def __setattr__(self, name: str, value: object) -> None:
        if (
            name == "disbursement_value_date"
            and name in self.__dict__
            and self.__dict__[name] is None
        ):
            object.__setattr__(self, name, value)
            return
        if name in _FROZEN_ACCOUNT_FIELDS and name in self.__dict__:
            raise LedgerError(
                "identity-frozen",
                "LOCKED_DECISIONS §16: name, identity number, service address, "
                "and the other facts frozen at booking are not rewritten.",
            )
        object.__setattr__(self, name, value)


@dataclass(frozen=True)
class Entry:
    account_code: str
    bucket: str | None
    debit_cents: int
    credit_cents: int


@dataclass(frozen=True)
class Effect:
    op: str
    cents: int = 0
    charge_id: str | None = None
    bucket: str | None = None
    due_on: date | None = None
    sequence: int | None = None
    year: int | None = None
    month: int | None = None
    episode_no: int | None = None
    levied_on: date | None = None
    ex_vat_cents: int = 0
    vat_cents: int = 0


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    organisation_id: str
    loan_id: str
    kind: str
    value_date: date
    recognised_at: datetime
    recognition_sequence: int
    reverses_transaction_id: str | None
    entries: tuple[Entry, ...]
    effects: tuple[Effect, ...]
    memo_rands: Decimal | None = None
    amount_cents: int | None = None
    attributed_due_on: date | None = None


@dataclass(frozen=True)
class Accrual:
    loan_id: str
    value_date: date
    base_cents: int
    principal_cents: int
    hold_cents: int
    weight: int
    periodic_rate: Decimal
    day_rands: Decimal
    transaction_id: str


@dataclass(frozen=True)
class StatementLine:
    loan_id: str
    opening: dict[str, int]
    closing: dict[str, int]


@dataclass(frozen=True)
class Statement:
    organisation_id: str
    person_id: str
    period_start: date
    period_end: date
    loans: tuple[StatementLine, ...]
