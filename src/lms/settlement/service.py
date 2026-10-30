"""Early-settlement quote and execute.

Quote order, from orchestration section 7:
1. Ledger.quote_settlement
2. Documents.settlement_quote

Execute accepts a receipt that matches that quote. Due amounts are
capitalised first, at 00:00 Africa/Johannesburg, and the receipt is then
allocated in section 126 order. The agreement is marked settled only when
the balance is R0.

A failure is returned with a specific reason and written to the audit log.
Amounts are integer cents. A missing required election or a missing NCR
number fails closed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from lms.calc.calendar import month_end
from lms.calc.models import RepoRate, VatRate
from lms.calc.money import RuleError
from lms.ledger.errors import LedgerError
from lms.ledger.models import LoanAccount
from lms.ledger.service import Ledger
from lms.servicing.errors import ServicingError
from lms.servicing.service import AgreementRecord, Servicing
from lms.settlement.errors import SettlementError
from lms.statements.errors import DocumentsError
from lms.statements.models import StoredQuote
from lms.statements.service import (
    Documents,
    _engine_agreement,
    _payment_events,
    _policy,
    _service_fee_cents,
)
from lms_config.calendar import value_date, value_instant
from lms_config.compliance import ComplianceStore
from lms_config.exceptions import CalculationInputError
from lms_config.locked import IN_DUPLUM_TRIGGERS

_ALLOCATABLE = {"active", "in_arrears"}


@dataclass(frozen=True)
class QuoteConfirmation:
    success: bool
    confirmation: str
    quote_id: str
    agreement_id: str
    amount_owing_cents: int
    valid_until: date
    ncr_registration_number: str
    early_termination_cents: int
    as_of: date
    delivered_on: date


@dataclass(frozen=True)
class SettlementConfirmation:
    success: bool
    confirmation: str
    agreement_id: str
    quote_id: str
    amount_cents: int
    balance_cents: int
    ncr_registration_number: str


@dataclass
class _HeldQuote:
    quote_id: str
    stored: StoredQuote
    ncr_registration_number: str


class Settlement:
    def __init__(
        self,
        servicing: Servicing,
        compliance: ComplianceStore,
        documents: Documents | None = None,
    ) -> None:
        self.servicing = servicing
        self.compliance = compliance
        self.documents = documents or Documents(servicing, compliance)
        self._quotes: dict[str, _HeldQuote] = {}
        self._by_inputs: dict[tuple[str, date, date], str] = {}
        self._idempotency: dict[tuple[str, str, str], tuple[str, SettlementConfirmation]] = {}

    @property
    def ledger(self) -> Ledger:
        return self.servicing.ledger

    def quote(
        self,
        *,
        agreement_id: str,
        as_of: date,
        delivered_on: date,
        request_on: date,
        recognised_at: datetime,
        holidays: frozenset[date] | None,
        interest_cap_present: bool,
        vat_rate: Decimal | None = None,
        repos: tuple[RepoRate, ...] = (),
    ) -> QuoteConfirmation:
        self._require_aware(recognised_at)
        record = self._record(agreement_id)
        try:
            return self._quote(
                record,
                as_of=as_of,
                delivered_on=delivered_on,
                request_on=request_on,
                recognised_at=recognised_at,
                holidays=holidays,
                interest_cap_present=interest_cap_present,
                vat_rate=vat_rate,
                repos=repos,
            )
        except SettlementError as exc:
            self._audit_failure(record, recognised_at, exc)
            raise

    def execute(
        self,
        *,
        agreement_id: str,
        quote_id: str,
        cents: int,
        recognised_at: datetime,
        interest_cap_present: bool,
        vat_rate: Decimal | None = None,
        idempotency_key: str,
        repos: tuple[RepoRate, ...] = (),
    ) -> SettlementConfirmation:
        self._require_aware(recognised_at)
        record = self._record(agreement_id)
        try:
            return self._execute(
                record,
                quote_id=quote_id,
                cents=cents,
                recognised_at=recognised_at,
                interest_cap_present=interest_cap_present,
                vat_rate=vat_rate,
                idempotency_key=idempotency_key,
                repos=repos,
            )
        except SettlementError as exc:
            self._audit_failure(record, recognised_at, exc)
            raise

    def _quote(
        self,
        record: AgreementRecord,
        *,
        as_of: date,
        delivered_on: date,
        request_on: date,
        recognised_at: datetime,
        holidays: frozenset[date] | None,
        interest_cap_present: bool,
        vat_rate: Decimal | None,
        repos: tuple[RepoRate, ...],
    ) -> QuoteConfirmation:
        self._require_disbursed(record)
        self._require_elections(record)
        self._require_cap(interest_cap_present)
        vat = self._require_vat(vat_rate)
        if holidays is None:
            raise SettlementError(
                "holidays-unset",
                "Public holidays were not supplied. No calendar is assumed.",
            )
        if repos:
            raise SettlementError(
                "repo-quote-unset",
                "Documents.settlement_quote does not take repo rows. "
                "A quote that needs them is not issued.",
            )
        ncr = self._ncr(record)
        account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        try:
            engine_quote = self.ledger.quote_settlement(
                _engine_agreement(record, account),
                _payment_events(self.ledger, account),
                as_of=as_of,
                delivered_on=delivered_on,
                policy=_policy(account, _service_fee_cents(record)),
                holidays=holidays,
                vat_rates=(VatRate(account.disbursement_value_date, vat),),
            )
        except (RuleError, CalculationInputError, LedgerError) as exc:
            code = getattr(exc, "code", None) or "quote"
            raise SettlementError(code, str(exc)) from exc
        if engine_quote.early_termination_cents != 0:
            raise SettlementError(
                "early-termination-unexpected",
                "Day-1 settlement quotes carry an early-termination charge of R0.",
            )
        stored = self._documents_quote(
            record,
            as_of=as_of,
            delivered_on=delivered_on,
            request_on=request_on,
            holidays=holidays,
            vat_rate=vat,
        )
        self._require_money(stored)
        if stored.total_cents != engine_quote.total_cents or stored.valid_until != engine_quote.valid_until:
            raise SettlementError(
                "quote-mismatch",
                "Documents.settlement_quote did not match Ledger.quote_settlement.",
            )
        if stored.early_termination_cents != 0:
            raise SettlementError(
                "early-termination-unexpected",
                "Day-1 settlement quotes carry an early-termination charge of R0.",
            )
        key = (record.agreement_id, as_of, delivered_on)
        quote_id = self._by_inputs.get(key)
        if quote_id is None:
            quote_id = str(uuid4())
            self._by_inputs[key] = quote_id
        self._quotes[quote_id] = _HeldQuote(quote_id, stored, ncr)
        confirmation = (
            f"Settlement quote issued. Amount owing is {stored.total_cents} cents, "
            f"valid until {stored.valid_until.isoformat()}. NCR number {ncr}."
        )
        self.servicing.audit.append(
            organisation_id=record.organisation_id,
            occurred_at=recognised_at,
            event_type="SETTLEMENT_QUOTED",
            category="operational",
            agreement_id=record.agreement_id,
            enigma_person_id=record.person_id,
            payload={
                "outcome": "success",
                "quote_id": quote_id,
                "amount_owing_cents": stored.total_cents,
                "valid_until": stored.valid_until.isoformat(),
                "ncr_registration_number": ncr,
                "early_termination_cents": 0,
            },
        )
        return QuoteConfirmation(
            success=True,
            confirmation=confirmation,
            quote_id=quote_id,
            agreement_id=record.agreement_id,
            amount_owing_cents=stored.total_cents,
            valid_until=stored.valid_until,
            ncr_registration_number=ncr,
            early_termination_cents=0,
            as_of=stored.as_of,
            delivered_on=stored.delivered_on,
        )

    def _execute(
        self,
        record: AgreementRecord,
        *,
        quote_id: str,
        cents: int,
        recognised_at: datetime,
        interest_cap_present: bool,
        vat_rate: Decimal | None,
        idempotency_key: str,
        repos: tuple[RepoRate, ...],
    ) -> SettlementConfirmation:
        if type(cents) is not int:
            raise SettlementError("cents", "Amounts are integer cents.")
        if not idempotency_key:
            raise SettlementError("idempotency-required", "Settlement execute requires an idempotency key.")
        fingerprint = f"{quote_id}:{cents}:{recognised_at.isoformat()}:{interest_cap_present}:{vat_rate}"
        replay_key = ("settlement", record.organisation_id, idempotency_key)
        stored_replay = self._idempotency.get(replay_key)
        if stored_replay is not None:
            previous, confirmation = stored_replay
            if previous != fingerprint:
                raise SettlementError(
                    "idempotency-conflict",
                    "This idempotency key was already used for a different settlement receipt.",
                    status=409,
                )
            return confirmation
        held = self._quotes.get(quote_id)
        if held is None or held.stored.agreement_id != record.agreement_id:
            raise SettlementError("quote-missing", "No settlement quote with that id exists for this agreement.")
        self._require_disbursed(record)
        if record.status not in _ALLOCATABLE:
            raise SettlementError("status", f"Cannot settle an agreement in {record.status}.")
        stored = held.stored
        if stored.early_termination_cents != 0:
            raise SettlementError(
                "early-termination-unexpected",
                "Day-1 settlement quotes carry an early-termination charge of R0.",
            )
        paid_on = value_date(recognised_at)
        if paid_on < stored.delivered_on or paid_on > stored.valid_until:
            raise SettlementError(
                "quote-window",
                f"The receipt value date {paid_on.isoformat()} is outside the quote window "
                f"{stored.delivered_on.isoformat()} to {stored.valid_until.isoformat()}.",
            )
        if cents != stored.total_cents:
            raise SettlementError(
                "quote-mismatch",
                f"Receipt of {cents} cents does not match the quoted amount owing of {stored.total_cents} cents.",
            )
        self._require_elections(record)
        self._require_cap(interest_cap_present)
        vat = self._require_vat(vat_rate)
        scratch = copy.deepcopy(self.ledger)
        self._capitalise_and_allocate(
            scratch,
            record,
            stored,
            cents=cents,
            recognised_at=recognised_at,
            vat_rate=vat,
            repos=repos,
        )
        scratch_account = scratch.store.get(record.organisation_id, record.ledger_loan_id or "")
        if _amount_owing(scratch_account) != 0:
            raise SettlementError(
                "settlement-balance",
                "The receipt does not bring the balance to R0. The agreement is not settled.",
            )
        self._capitalise_and_allocate(
            self.ledger,
            record,
            stored,
            cents=cents,
            recognised_at=recognised_at,
            vat_rate=vat,
            repos=repos,
        )
        account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        balance = _amount_owing(account)
        if balance != 0:
            raise SettlementError(
                "settlement-balance",
                f"The balance after the receipt is {balance} cents, not R0. The agreement is not settled.",
            )
        self.servicing._refresh_status(record)
        if record.status != "settled":
            raise SettlementError(
                "settlement-balance",
                "The balance is R0 but the agreement was not marked settled.",
            )
        confirmation = SettlementConfirmation(
            success=True,
            confirmation=(
                f"Agreement settled. Receipt of {cents} cents allocated in section 126 order. "
                "Balance is 0 cents."
            ),
            agreement_id=record.agreement_id,
            quote_id=quote_id,
            amount_cents=cents,
            balance_cents=0,
            ncr_registration_number=held.ncr_registration_number,
        )
        self._idempotency[replay_key] = (fingerprint, confirmation)
        self.servicing.audit.append(
            organisation_id=record.organisation_id,
            occurred_at=recognised_at,
            event_type="SETTLEMENT_APPLIED",
            category="financial",
            amount_cents=cents,
            agreement_id=record.agreement_id,
            enigma_person_id=record.person_id,
            payload={
                "outcome": "success",
                "quote_id": quote_id,
                "balance_cents": 0,
                "ncr_registration_number": held.ncr_registration_number,
                "value_date": paid_on.isoformat(),
            },
        )
        self.servicing.audit.append(
            organisation_id=record.organisation_id,
            occurred_at=recognised_at,
            event_type="AGREEMENT_STATUS_CHANGED",
            category="operational",
            agreement_id=record.agreement_id,
            enigma_person_id=record.person_id,
            payload={"outcome": "success", "status": "settled", "quote_id": quote_id},
        )
        return confirmation

    def _documents_quote(
        self,
        record: AgreementRecord,
        *,
        as_of: date,
        delivered_on: date,
        request_on: date,
        holidays: frozenset[date],
        vat_rate: Decimal,
    ) -> StoredQuote:
        try:
            return self.documents.settlement_quote(
                agreement_id=record.agreement_id,
                as_of=as_of,
                delivered_on=delivered_on,
                request_on=request_on,
                holidays=holidays,
                vat_rate=vat_rate,
            )
        except (DocumentsError, LedgerError, ServicingError, CalculationInputError, RuleError) as exc:
            code = getattr(exc, "code", None) or "quote"
            raise SettlementError(code, str(exc)) from exc

    def _capitalise_and_allocate(
        self,
        ledger: Ledger,
        record: AgreementRecord,
        stored: StoredQuote,
        *,
        cents: int,
        recognised_at: datetime,
        vat_rate: Decimal,
        repos: tuple[RepoRate, ...],
    ) -> None:
        account = ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        as_of = stored.as_of
        if account.disbursement_value_date is None:
            raise SettlementError("status", "The agreement has not been disbursed.")
        if as_of < account.disbursement_value_date or as_of > account.contractual_end:
            raise SettlementError(
                "outside-term",
                "Interest is not accrued outside the disbursement date and the contractual end.",
            )
        self._accrue_through(ledger, record, account, as_of, vat_rate, repos)
        account = ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        owing = _amount_owing(account)
        if owing != stored.total_cents:
            quoted_initiation = dict(stored.components).get("initiation", 0)
            booked_initiation = ledger.bucket_balance(account, "initiation")
            detail = (
                f"After capitalising to {as_of.isoformat()}, the ledger amount owing is {owing} cents "
                f"and the quote is {stored.total_cents} cents."
            )
            if quoted_initiation != booked_initiation:
                detail += (
                    f" Quoted initiation is {quoted_initiation} cents and the ledger initiation balance "
                    f"is {booked_initiation} cents. The booked fee and the statutory formula are not "
                    "the same, and the difference was not posted."
                )
            raise SettlementError("quote-mismatch", detail + " The receipt was not allocated.")
        try:
            ledger.post_settlement(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                cents=cents,
                recognised_at=value_instant(value_date(recognised_at)),
            )
        except LedgerError as exc:
            raise SettlementError(exc.code, str(exc)) from exc

    def _accrue_through(
        self,
        ledger: Ledger,
        record: AgreementRecord,
        account: LoanAccount,
        as_of: date,
        vat_rate: Decimal,
        repos: tuple[RepoRate, ...],
    ) -> None:
        start = account.disbursement_value_date
        if start is None:
            raise SettlementError("status", "The agreement has not been disbursed.")
        monthly = _service_fee_cents(record)
        first_due = min(due for due, _amount in record.schedule)
        day = start
        while day <= as_of:
            try:
                ledger.accrue_day(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(day),
                    interest_cap_present=True,
                    repos=repos,
                )
            except LedgerError as exc:
                if exc.code not in {"already-accrued", "outside-term"}:
                    raise SettlementError(exc.code, str(exc)) from exc
            except CalculationInputError as exc:
                raise SettlementError("reference-missing", str(exc)) from exc
            if day == month_end(day) or day == as_of:
                try:
                    ledger.bill_interest(
                        organisation_id=record.organisation_id,
                        loan_id=account.loan_id,
                        recognised_at=value_instant(day),
                    )
                except LedgerError as exc:
                    raise SettlementError(exc.code, str(exc)) from exc
                if monthly:
                    opening = day.year == start.year and day.month == start.month and first_due > start
                    try:
                        ledger.levy_service_fee(
                            organisation_id=record.organisation_id,
                            loan_id=account.loan_id,
                            recognised_at=value_instant(day),
                            monthly_cents=monthly,
                            due_on=first_due if opening else day,
                            interest_cap_present=True,
                            vat_rate=vat_rate,
                            opening=opening,
                            first_due=first_due if opening else None,
                        )
                    except LedgerError as exc:
                        if exc.code != "service-fee-once":
                            raise SettlementError(exc.code, str(exc)) from exc
            day += timedelta(days=1)

    def _require_disbursed(self, record: AgreementRecord) -> None:
        if record.ledger_loan_id is None or record.disbursement_value_date is None:
            raise SettlementError("status", "The agreement has not been disbursed.")

    def _require_elections(self, record: AgreementRecord) -> None:
        if record.resolved.in_duplum_trigger not in IN_DUPLUM_TRIGGERS:
            raise SettlementError("election-unset", "missing election: in_duplum_trigger")
        account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        snapshot = account.snapshot
        if snapshot.day_count_code not in {"actual_actual", "30_360"}:
            raise SettlementError("election-unset", "missing election: day count")
        if snapshot.vat_on_rand_maxima not in {"exclusive", "inclusive"}:
            raise SettlementError("election-unset", "missing election: vat on rand maxima")
        if snapshot.repo_rate_fall not in {"contract_rate", "lower_of_contract_and_cap"}:
            raise SettlementError("election-unset", "missing election: repo-rate fall")
        if snapshot.interest_on_deferred_initiation not in {"none", "permitted"}:
            raise SettlementError(
                "election-unset",
                "missing election: interest on deferred initiation fee",
            )
        if snapshot.leniency_days is None or snapshot.leniency_days < 0:
            raise SettlementError("election-unset", "missing election: leniency days")
        if snapshot.full_payment_threshold_percent is None:
            raise SettlementError("election-unset", "missing election: full payment threshold")

    def _ncr(self, record: AgreementRecord) -> str:
        account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        if account.snapshot.classification not in {"short_term", "unsecured"}:
            raise SettlementError(
                "quote-classification",
                "A section 113 quote is only built for a short-term or unsecured agreement. "
                "No lay-by settlement formula is added here.",
            )
        try:
            row = self.compliance.require(record.organisation_id)
        except CalculationInputError as exc:
            text = str(exc)
            if "ncr_registration_number" in text or "no LMS compliance row" in text:
                raise SettlementError("ncr-missing", f"missing NCR number: {text}") from exc
            raise SettlementError("compliance-missing", text) from exc
        number = row.ncr_registration_number.strip()
        if not number:
            raise SettlementError("ncr-missing", "missing NCR number")
        return number

    def _record(self, agreement_id: str) -> AgreementRecord:
        record = self.servicing.agreements.get(agreement_id)
        if record is None:
            raise SettlementError("not-found", "No agreement with that id.", status=404)
        return record

    def _audit_failure(
        self,
        record: AgreementRecord,
        recognised_at: datetime,
        exc: SettlementError,
    ) -> None:
        self.servicing.audit.append(
            organisation_id=record.organisation_id,
            occurred_at=recognised_at,
            event_type="SETTLEMENT_REJECTED",
            category="operational",
            agreement_id=record.agreement_id,
            enigma_person_id=record.person_id,
            payload={"outcome": "failure", "code": exc.code, "reason": str(exc)},
        )

    def _require_aware(self, recognised_at: datetime) -> None:
        if recognised_at.tzinfo is None:
            raise SettlementError(
                "timestamp-naive",
                "Recognition timestamp must be timezone-aware. "
                "The value date is 00:00 Africa/Johannesburg on that calendar day.",
            )

    def _require_cap(self, interest_cap_present: bool) -> None:
        if interest_cap_present is not True:
            raise SettlementError("interest-cap-missing", "no interest cap covers the value date")

    def _require_vat(self, vat_rate: Decimal | None) -> Decimal:
        if not isinstance(vat_rate, Decimal):
            raise SettlementError(
                "vat-rate-unset",
                "LOCKED_DECISIONS §9 does not store a VAT rate. "
                "The settlement fails closed until the caller supplies one.",
            )
        if vat_rate < 0:
            raise SettlementError("vat-rate", "The VAT rate cannot be negative.")
        return vat_rate

    def _require_money(self, stored: StoredQuote) -> None:
        amounts = (
            stored.principal_cents,
            stored.interest_cents,
            stored.fee_cents,
            stored.early_termination_cents,
            stored.total_cents,
        )
        if any(type(amount) is not int for amount in amounts):
            raise SettlementError("cents", "Amounts are integer cents.")
        if stored.total_cents != (
            stored.principal_cents
            + stored.interest_cents
            + stored.fee_cents
            + stored.early_termination_cents
        ):
            raise SettlementError(
                "quote-mismatch",
                "The quoted total is not the sum of principal, interest, fees, and early termination.",
            )


def _amount_owing(account: LoanAccount) -> int:
    return sum(slice_.remaining_cents for slice_ in account.slices) + sum(
        charge.remaining_cents for charge in account.charges
    )
