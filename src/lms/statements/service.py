"""Statements and the section 110 and section 113 documents.

Calls the ledger, LMS configuration, servicing, and the calculation engine.
Does not re-implement interest, fees, allocation, settlement arithmetic, or
business-day counting.

Locked decisions are cited on the calls. Gaps are raised and left empty.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from lms.calc.calendar import binding_until, month_end
from lms.calc.interest import nominal_annual_rate, periods_per_year
from lms.calc.ledger import quote_settlement
from lms.calc.models import (
    Agreement,
    FeeCapBasis,
    Payment,
    Policy,
    Product,
    TerminalServiceFee,
    VatRate,
)
from lms.calc.money import RuleError
from lms.ledger.errors import LedgerError
from lms.ledger.models import BUCKETS, LoanAccount
from lms.ledger.service import Ledger, _day_count, _prepayment, _repo_fall
from lms.servicing.service import AgreementRecord, Servicing
from lms.statements.errors import DocumentsError
from lms.statements.models import AmountOwing, LoanSection, StoredQuote, StoredStatement, TransactionView
from lms_config.calendar import add_business_days, value_date, value_instant
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.exceptions import CalculationInputError
from lms_config.locked import campaign_rate
from lms_config.statute import DAY_COUNT_ACTUAL_ACTUAL, DAY_COUNT_30_360

_ACTIVE = {"active", "in_arrears", "settled"}
_FEE_BUCKETS = (
    "initiation",
    "service",
    "credit_insurance",
    "default_administration",
    "collection_costs",
    "additional_monthly",
)
_OWING_BUCKETS = ("principal", "interest", *_FEE_BUCKETS)


@dataclass(frozen=True)
class RecognisedReceipt:
    """A receipt the statement run allocates after that day's capitalisation.

    ``recognised_at`` is the system recognition time (locked decision 1).
    The value date is the Johannesburg calendar date of that instant.
    """

    agreement_id: str
    cents: int
    recognised_at: datetime
    attributed_due_on: date
    idempotency_key: str


class Documents:
    def __init__(self, servicing: Servicing, compliance: ComplianceStore) -> None:
        self.servicing = servicing
        self.compliance = compliance
        self.statements: dict[tuple[str, str, date, date], StoredStatement] = {}
        self.quotes: dict[tuple[str, date, date], StoredQuote] = {}

    @property
    def ledger(self) -> Ledger:
        return self.servicing.ledger

    def issue_statement(
        self,
        *,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
        interest_cap_present: bool,
        vat_rate: Decimal | None = None,
        receipts: tuple[RecognisedReceipt, ...] = (),
    ) -> StoredStatement:
        """One statement per person per organisation (locked decision 12).

        On each day in the period, at 00:00: accrue, capitalise amounts the
        engine treats as due, then allocate receipts recognised that day
        (locked decisions 1 and 8). The stored statement is returned again
        on a repeat of the same period and is not rebuilt.
        """
        self._mandate(organisation_id, person_id, "statement.issue")
        if period_end < period_start:
            raise DocumentsError("statement-period", "The statement period ends before it starts.")
        key = (organisation_id, person_id, period_start, period_end)
        existing = self.statements.get(key)
        if existing is not None:
            return existing
        self._refuse_overlap(organisation_id, person_id, period_start, period_end)
        provider = self._provider(organisation_id)
        agreements = self._agreements(organisation_id, person_id)
        if not agreements:
            raise DocumentsError("no-loan", "This client has no disbursed loan at this organisation.")
        by_day = self._receipts_by_day(receipts, agreements, period_start, period_end)
        self._require_vat_before_posting(agreements, period_start, period_end, vat_rate)
        for record in agreements:
            self._fold(record, period_start, period_end, by_day, vat_rate, interest_cap_present)
        sections = tuple(
            self._section(account, period_start, period_end, organisation_id, person_id)
            for account in self._accounts(organisation_id, person_id)
        )
        self._check_chain(organisation_id, person_id, period_start, sections)
        try:
            self.ledger.issue_statement(
                organisation_id=organisation_id,
                person_id=person_id,
                period_start=period_start,
                period_end=period_end,
            )
        except LedgerError as exc:
            raise _from_ledger(exc) from exc
        stored = _freeze(
            organisation_id=organisation_id,
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
            provider=provider,
            loans=sections,
        )
        self.statements[key] = stored
        self.servicing.audit.append(
            organisation_id=organisation_id,
            occurred_at=value_instant(period_end),
            event_type="STATEMENT_ISSUED",
            category="operational",
            enigma_person_id=person_id,
            payload={
                "statement_id": stored.statement_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        return stored

    def enquire(
        self,
        *,
        organisation_id: str,
        person_id: str,
        loan_id: str,
        request_on: date,
        holidays: frozenset[date],
        interest_cap_present: bool,
        period_start: date | None = None,
        period_end: date | None = None,
        vat_rate: Decimal | None = None,
    ) -> AmountOwing:
        """Section 110 amount owing. Does not call ``Ledger.issue_statement``."""
        self._mandate(organisation_id, person_id, "statement.enquire")
        if holidays is None:
            raise DocumentsError("holidays-unset", "Public holidays were not supplied. No calendar is assumed.")
        record = self._agreement_for_loan(organisation_id, person_id, loan_id)
        account = self.ledger.store.get(organisation_id, loan_id)
        self._fold(record, account.disbursement_value_date, request_on, {}, vat_rate, interest_cap_present)
        components = _components(self.ledger, account, request_on)
        overdue = _aged(account, request_on, before=True)
        payable = _aged(account, request_on, before=False)
        movements: tuple[TransactionView, ...] = ()
        if period_start is not None or period_end is not None:
            if period_start is None or period_end is None or period_end < period_start:
                raise DocumentsError("enquiry-period", "A movement request needs a start and an end.")
            movements = _transactions(self.ledger, account, period_start, period_end)
        window = 20 if period_start is not None and period_start < _anniversary(request_on) else 10
        return AmountOwing(
            organisation_id=organisation_id,
            person_id=person_id,
            loan_id=loan_id,
            request_on=request_on,
            components=components,
            overdue=overdue,
            payable=payable,
            transactions=movements,
            deliver_by=add_business_days(request_on, window, holidays),
        )

    def settlement_quote(
        self,
        *,
        agreement_id: str,
        as_of: date,
        delivered_on: date,
        request_on: date,
        holidays: frozenset[date],
        vat_rate: Decimal | None = None,
    ) -> StoredQuote:
        """Section 113 quote from ``quote_settlement``. Day-1 early termination is R0.

        ``valid_until`` is the engine's ``binding_until`` result: five business
        days after delivery. This method does not post the settlement.
        """
        record = self.servicing.agreements.get(agreement_id)
        if record is None:
            raise DocumentsError("not-found", "No agreement with that id.")
        self._mandate(record.organisation_id, record.person_id, "settlement.quote")
        if holidays is None:
            raise DocumentsError("holidays-unset", "Public holidays were not supplied. No calendar is assumed.")
        if record.ledger_loan_id is None or record.disbursement_value_date is None:
            raise DocumentsError("status", "The agreement has not been disbursed.")
        cached = self.quotes.get((agreement_id, as_of, delivered_on))
        if cached is not None:
            return cached
        account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id)
        if account.snapshot.classification not in {"short_term", "unsecured"}:
            raise DocumentsError(
                "quote-classification",
                "A section 113 quote is only built for a short-term or unsecured agreement. "
                "No lay-by settlement formula is added here.",
            )
        agreement = _engine_agreement(record, account)
        policy = _policy(account, _service_fee_cents(record))
        events = _payment_events(self.ledger, account)
        vat_rates = (VatRate(account.disbursement_value_date, vat_rate),) if vat_rate is not None else None
        try:
            kwargs = dict(
                as_of=as_of,
                delivered_on=delivered_on,
                policy=policy,
                holidays=holidays,
            )
            if vat_rates is not None:
                kwargs["vat_rates"] = vat_rates
            quote = quote_settlement(agreement, events, **kwargs)
        except (RuleError, CalculationInputError) as exc:
            code = getattr(exc, "code", None) or "quote"
            raise DocumentsError(code, str(exc)) from exc
        if quote.early_termination_cents != 0:
            raise DocumentsError(
                "early-termination-unexpected",
                "Day-1 settlement quotes carry an early-termination charge of R0. "
                "The engine returned a non-zero charge. This layer does not keep it.",
            )
        # The engine already set valid_until via binding_until. Re-read that
        # function only to refuse a quote whose date does not match it.
        expected = binding_until(delivered_on, holidays)
        if quote.valid_until != expected:
            raise DocumentsError(
                "binding-window",
                "The quote's valid-until date is not binding_until(delivered_on).",
            )
        stored = StoredQuote(
            agreement_id=agreement_id,
            organisation_id=record.organisation_id,
            person_id=record.person_id,
            as_of=quote.as_of,
            delivered_on=quote.delivered_on,
            valid_until=quote.valid_until,
            deliver_by=add_business_days(request_on, 5, holidays),
            principal_cents=quote.principal_cents,
            interest_cents=quote.interest_cents,
            fee_cents=quote.fee_cents,
            early_termination_cents=0,
            total_cents=quote.total_cents,
            agreement_size=quote.agreement_size,
            components=quote.components,
        )
        self.quotes[(agreement_id, as_of, delivered_on)] = stored
        return stored

    def _mandate(self, organisation_id: str, person_id: str, action: str) -> None:
        # Locked decision 15. The servicing stub is the port servicing already uses.
        self.servicing.enigma.check(organisation_id, person_id, action)

    def _provider(self, organisation_id: str) -> ProviderCompliance:
        try:
            return self.compliance.require(organisation_id)
        except CalculationInputError as exc:
            raise DocumentsError("compliance-missing", str(exc)) from exc

    def _agreements(self, organisation_id: str, person_id: str) -> tuple[AgreementRecord, ...]:
        found = [
            record
            for record in self.servicing.agreements.values()
            if record.organisation_id == organisation_id
            and record.person_id == person_id
            and record.ledger_loan_id is not None
            and record.status in _ACTIVE
        ]
        return tuple(sorted(found, key=lambda record: record.ledger_loan_id or ""))

    def _accounts(self, organisation_id: str, person_id: str) -> tuple[LoanAccount, ...]:
        return tuple(
            sorted(
                (
                    account
                    for account in self.ledger.store.accounts_for(organisation_id)
                    if account.person_id == person_id
                ),
                key=lambda account: account.loan_id,
            )
        )

    def _agreement_for_loan(self, organisation_id: str, person_id: str, loan_id: str) -> AgreementRecord:
        for record in self._agreements(organisation_id, person_id):
            if record.ledger_loan_id == loan_id:
                return record
        raise DocumentsError("not-found", "No disbursed agreement for that loan.")

    def _refuse_overlap(self, organisation_id: str, person_id: str, period_start: date, period_end: date) -> None:
        for start, end in self.ledger.store.statement_keys(organisation_id, person_id):
            if start <= period_end and period_start <= end:
                raise DocumentsError(
                    "statement-exists",
                    "LOCKED_DECISIONS §12: one statement per client per credit-provider organisation. "
                    "An overlapping period is refused.",
                )

    def _receipts_by_day(
        self,
        receipts: tuple[RecognisedReceipt, ...],
        agreements: tuple[AgreementRecord, ...],
        period_start: date,
        period_end: date,
    ) -> dict[date, tuple[tuple[AgreementRecord, RecognisedReceipt], ...]]:
        by_id = {record.agreement_id: record for record in agreements}
        grouped: dict[date, list[tuple[AgreementRecord, RecognisedReceipt]]] = {}
        ordered = sorted(receipts, key=lambda item: item.recognised_at)
        for receipt in ordered:
            record = by_id.get(receipt.agreement_id)
            if record is None:
                raise DocumentsError(
                    "receipt-agreement",
                    "A statement-date receipt names an agreement that is not on this statement.",
                )
            day = value_date(receipt.recognised_at)
            if day < period_start or day > period_end:
                raise DocumentsError(
                    "receipt-period",
                    "A receipt recognised outside the statement period is not allocated by this run.",
                )
            grouped.setdefault(day, []).append((record, receipt))
        return {day: tuple(items) for day, items in grouped.items()}

    def _require_vat_before_posting(
        self,
        agreements: tuple[AgreementRecord, ...],
        period_start: date,
        period_end: date,
        vat_rate: Decimal | None,
    ) -> None:
        # Locked decision 9 does not store a VAT rate. Refuse before any accrual
        # so a missing rate does not debit interest.
        if vat_rate is not None:
            return
        for record in agreements:
            account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
            start = max(period_start, account.disbursement_value_date)
            end = min(period_end, account.contractual_end)
            if _service_fee_cents(record) and start <= end and _covers_month_end(start, end):
                raise DocumentsError(
                    "vat-rate-unset",
                    "LOCKED_DECISIONS §9 does not store a VAT rate. "
                    "A service-fee levy fails closed until the caller supplies one.",
                )

    def _fold(
        self,
        record: AgreementRecord,
        period_start: date,
        period_end: date,
        by_day: dict[date, tuple[tuple[AgreementRecord, RecognisedReceipt], ...]],
        vat_rate: Decimal | None,
        interest_cap_present: bool,
    ) -> None:
        account = self.ledger.store.get(record.organisation_id, record.ledger_loan_id or "")
        if account.instrument_kind != "loan":
            return
        start = max(period_start, account.disbursement_value_date)
        end = min(period_end, account.contractual_end)
        if start > end:
            return
        if _service_fee_cents(record) and vat_rate is None and _covers_month_end(start, end):
            raise DocumentsError(
                "vat-rate-unset",
                "LOCKED_DECISIONS §9 does not store a VAT rate. "
                "A service-fee levy fails closed until the caller supplies one.",
            )
        day = start
        while day <= end:
            self._morning(record, account, day)
            self._accrue(record, account, day, interest_cap_present)
            self._capitalise(record, account, day, vat_rate, interest_cap_present)
            for owner, receipt in by_day.get(day, ()):
                if owner.agreement_id != record.agreement_id:
                    continue
                self.servicing.accept_payment(
                    organisation_id=record.organisation_id,
                    person_id=record.person_id,
                    cents=receipt.cents,
                    recognised_at=receipt.recognised_at,
                    idempotency_key=receipt.idempotency_key,
                    agreement_id=record.agreement_id,
                    attributed_due_on=receipt.attributed_due_on,
                )
            day += timedelta(days=1)

    def _morning(self, record: AgreementRecord, account: LoanAccount, day: date) -> None:
        # Locked decision 6: flag only on the contractual due date plus leniency.
        for due_on, _amount in record.schedule:
            flag_on = due_on + timedelta(days=account.snapshot.leniency_days)
            if day == flag_on:
                self.servicing.morning_check(
                    record.agreement_id,
                    due_on=due_on,
                    recognised_at=value_instant(day),
                )

    def _accrue(
        self,
        record: AgreementRecord,
        account: LoanAccount,
        day: date,
        interest_cap_present: bool,
    ) -> None:
        try:
            self.ledger.accrue_day(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(day),
                interest_cap_present=interest_cap_present,
            )
        except LedgerError as exc:
            if exc.code not in {"already-accrued", "outside-term"}:
                raise _from_ledger(exc) from exc

    def _capitalise(
        self,
        record: AgreementRecord,
        account: LoanAccount,
        day: date,
        vat_rate: Decimal | None,
        interest_cap_present: bool,
    ) -> None:
        # Locked decisions 1 and 8. The engine bills interest and levies the
        # service fee on month-end (and on a settlement as-of, which is the
        # quote path, not this run). A statement date that is not a month-end
        # does not debit unbilled interest.
        if day != month_end(day):
            return
        try:
            self.ledger.bill_interest(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(day),
            )
        except LedgerError as exc:
            raise _from_ledger(exc) from exc
        monthly = _service_fee_cents(record)
        if monthly == 0:
            return
        if vat_rate is None:
            raise DocumentsError(
                "vat-rate-unset",
                "LOCKED_DECISIONS §9 does not store a VAT rate. "
                "A service-fee levy fails closed until the caller supplies one.",
            )
        first_due = min(due for due, _amount in record.schedule)
        opening = (
            day.year == account.disbursement_value_date.year
            and day.month == account.disbursement_value_date.month
            and first_due > account.disbursement_value_date
        )
        try:
            self.ledger.levy_service_fee(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(day),
                monthly_cents=monthly,
                due_on=first_due if opening else day,
                interest_cap_present=interest_cap_present,
                vat_rate=vat_rate,
                opening=opening,
                first_due=first_due if opening else None,
            )
        except LedgerError as exc:
            if exc.code != "service-fee-once":
                raise _from_ledger(exc) from exc

    def _section(
        self,
        account: LoanAccount,
        period_start: date,
        period_end: date,
        organisation_id: str,
        person_id: str,
    ) -> LoanSection:
        previous = _previous(self.statements, organisation_id, person_id, period_start)
        previous_section = None
        if previous is not None:
            previous_section = next((item for item in previous.loans if item.loan_id == account.loan_id), None)
        opening: dict[str, int] = {}
        closing: dict[str, int] = {}
        for bucket in BUCKETS:
            closing[bucket] = self.ledger.bucket_balance(account, bucket, as_of=period_end)
            if previous_section is not None:
                opening[bucket] = previous_section.closing[bucket]
                source = "previous-closing"
            else:
                opening[bucket] = self.ledger.bucket_balance(
                    account, bucket, as_of=period_start - timedelta(days=1)
                )
                source = "no-previous-statement"
        if previous_section is not None:
            for bucket in BUCKETS:
                ledger_opening = self.ledger.bucket_balance(
                    account, bucket, as_of=period_start - timedelta(days=1)
                )
                if opening[bucket] != ledger_opening:
                    raise DocumentsError(
                        "opening-chain",
                        "LOCKED_DECISIONS §12 and section 109 require this opening to equal "
                        "the previous stored closing. The ledger balance on the day before "
                        "this period does not match that closing. No adjustment line is invented.",
                    )
        movements = _transactions(self.ledger, account, period_start, period_end)
        base = account.snapshot.base_rate
        discount = account.snapshot.discount_rate
        nominal_base, nominal_effective, in_force = _nominals(account)
        instalment_cents, instalment_due = _instalment(account, period_end)
        return LoanSection(
            loan_id=account.loan_id,
            instrument_kind=account.instrument_kind,
            parent_loan_id=account.parent_loan_id,
            frozen_full_name=account.frozen_full_name,
            frozen_id_number=account.frozen_id_number,
            frozen_service_address=account.frozen_service_address,
            payment_frequency=account.payment_frequency,
            principal_debt_cents=account.cash_advanced_cents + account.capitalised_initiation_cents,
            opening=opening,
            closing=closing,
            opening_source=source,
            base_rate=base,
            discount_rate=discount,
            discount_fallen_away=account.discount_fallen_away,
            periodic_rate_in_force=in_force,
            nominal_annual_on_base=nominal_base,
            nominal_annual_on_effective=nominal_effective,
            annual_rate_cell=None,
            instalment_cents=instalment_cents,
            instalment_due_on=instalment_due,
            payments_received_cents=_signed(movements, kind="payment"),
            fees_levied_cents=sum(_bucket_movement(movements, bucket) for bucket in ("initiation", "service", "additional_monthly")),
            interest_billed_cents=_bucket_movement(movements, "interest"),
            interest_memo_rands=sum(
                (line.memo_rands or Decimal(0))
                for line in movements
                if line.kind == "interest_accrual"
            ),
            insurance_levied_cents=_bucket_movement(movements, "credit_insurance"),
            collection_levied_cents=_bucket_movement(movements, "collection_costs"),
            default_administration_levied_cents=_bucket_movement(movements, "default_administration"),
            legal_fees_cents=None,
            arrears_cents=None,
            overdue=_aged(account, period_end, before=True),
            open_default_episode=any(episode.closed_on is None for episode in account.episodes),
            transactions=movements,
        )

    def _check_chain(
        self,
        organisation_id: str,
        person_id: str,
        period_start: date,
        sections: tuple[LoanSection, ...],
    ) -> None:
        previous = _previous(self.statements, organisation_id, person_id, period_start)
        if previous is None:
            return
        if period_start > previous.period_end + timedelta(days=1):
            for section in sections:
                for transaction in self.ledger.store.transactions_for(organisation_id, section.loan_id):
                    if previous.period_end < transaction.value_date < period_start:
                        raise DocumentsError(
                            "statement-gap",
                            "A value date between two statements has ledger entries and would appear "
                            "on neither statement. The period is refused.",
                        )
        for section in sections:
            prior = next((item for item in previous.loans if item.loan_id == section.loan_id), None)
            if prior is None:
                continue
            if section.opening != prior.closing:
                raise DocumentsError(
                    "opening-chain",
                    "LOCKED_DECISIONS §12: each loan's opening balance is its previous closing balance.",
                )


def _freeze(
    *,
    organisation_id: str,
    person_id: str,
    period_start: date,
    period_end: date,
    provider: ProviderCompliance,
    loans: tuple[LoanSection, ...],
) -> StoredStatement:
    payload = {
        "organisation_id": organisation_id,
        "person_id": person_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "legal_name": provider.legal_name,
        "ncr_registration_number": provider.ncr_registration_number,
        "trading_name": provider.trading_name,
        "physical_address": provider.physical_address,
        "postal_address": provider.postal_address,
        "telephone": provider.telephone,
        "bank_name": provider.bank_name,
        "bank_account_number": provider.bank_account_number,
        "branch_code": provider.branch_code,
        "payment_reference": provider.payment_reference,
        "loans": [
            {
                "loan_id": section.loan_id,
                "opening": section.opening,
                "closing": section.closing,
                "base_rate": str(section.base_rate),
                "discount_rate": str(section.discount_rate),
            }
            for section in loans
        ],
    }
    body = json.dumps(payload, sort_keys=True).encode()
    stub = b"PDF-STUB\n" + body
    return StoredStatement(
        statement_id=str(uuid4()),
        organisation_id=organisation_id,
        person_id=person_id,
        period_start=period_start,
        period_end=period_end,
        statement_date=period_end,
        legal_name=provider.legal_name,
        ncr_registration_number=provider.ncr_registration_number,
        trading_name=provider.trading_name,
        physical_address=provider.physical_address,
        postal_address=provider.postal_address,
        telephone=provider.telephone,
        bank_name=provider.bank_name,
        bank_account_number=provider.bank_account_number,
        branch_code=provider.branch_code,
        payment_reference=provider.payment_reference,
        loans=loans,
        pdf_sha256=hashlib.sha256(stub).hexdigest(),
        pdf_stub=stub,
    )


def _components(ledger: Ledger, account: LoanAccount, as_of: date) -> dict[str, int]:
    return {bucket: ledger.bucket_balance(account, bucket, as_of=as_of) for bucket in BUCKETS}


def _aged(account: LoanAccount, request_on: date, *, before: bool) -> tuple[tuple[str, date, int], ...]:
    rows: list[tuple[str, date, int]] = []
    for charge in account.charges:
        if charge.remaining_cents <= 0:
            continue
        due = charge.due_on < request_on if before else charge.due_on <= request_on
        if due:
            rows.append((charge.bucket, charge.due_on, charge.remaining_cents))
    for slice_ in account.slices:
        if slice_.remaining_cents <= 0:
            continue
        due = slice_.due_on < request_on if before else slice_.due_on <= request_on
        if due:
            rows.append(("principal", slice_.due_on, slice_.remaining_cents))
    return tuple(sorted(rows, key=lambda item: (item[1], item[0])))


def _transactions(ledger: Ledger, account: LoanAccount, start: date, end: date) -> tuple[TransactionView, ...]:
    lines: list[TransactionView] = []
    for transaction in ledger.store.transactions_for(account.organisation_id, account.loan_id):
        if transaction.value_date < start or transaction.value_date > end:
            continue
        if transaction.memo_rands is not None and not transaction.entries:
            lines.append(
                TransactionView(
                    loan_id=account.loan_id,
                    value_date=transaction.value_date,
                    recognition_sequence=transaction.recognition_sequence,
                    kind=transaction.kind,
                    bucket=None,
                    debit_cents=0,
                    credit_cents=0,
                    memo_rands=transaction.memo_rands,
                    description=transaction.kind,
                )
            )
        for entry in transaction.entries:
            if entry.bucket is None:
                continue
            lines.append(
                TransactionView(
                    loan_id=account.loan_id,
                    value_date=transaction.value_date,
                    recognition_sequence=transaction.recognition_sequence,
                    kind=transaction.kind,
                    bucket=entry.bucket,
                    debit_cents=entry.debit_cents,
                    credit_cents=entry.credit_cents,
                    memo_rands=None,
                    description=f"{transaction.kind} {entry.bucket}",
                )
            )
    return tuple(sorted(lines, key=lambda line: (line.value_date, line.recognition_sequence, line.bucket or "")))


def _previous(
    statements: dict[tuple[str, str, date, date], StoredStatement],
    organisation_id: str,
    person_id: str,
    period_start: date,
) -> StoredStatement | None:
    candidates = [
        statement
        for (org, person, _start, end), statement in statements.items()
        if org == organisation_id and person == person_id and end < period_start
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda statement: statement.period_end)


def _nominals(account: LoanAccount) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    snapshot = account.snapshot
    if snapshot.classification not in {"short_term", "unsecured"}:
        return None, None, None
    if snapshot.classification == "unsecured" and snapshot.discount_rate != 0:
        # The ledger already refuses this at accrual. Disclosure does not pick a base.
        return None, None, None
    product = Product.MICRO if snapshot.classification == "short_term" else Product.PERSONAL
    try:
        in_force = campaign_rate(
            snapshot.base_rate,
            snapshot.discount_rate,
            discount_fallen_away=account.discount_fallen_away,
        )
        count = periods_per_year(product)
    except (RuleError, CalculationInputError) as exc:
        code = getattr(exc, "code", None) or "disclosure"
        raise DocumentsError(code, str(exc)) from exc
    return (
        nominal_annual_rate(snapshot.base_rate, count),
        nominal_annual_rate(in_force, count),
        in_force,
    )


def _instalment(account: LoanAccount, statement_date: date) -> tuple[int | None, date | None]:
    upcoming = [slice_ for slice_ in account.slices if slice_.due_on >= statement_date]
    chosen = min(upcoming, key=lambda slice_: slice_.due_on) if upcoming else None
    if chosen is None and account.slices:
        chosen = max(account.slices, key=lambda slice_: slice_.due_on)
    if chosen is None:
        return None, None
    # Locked decision 6: the instalment is the original principal slice plus
    # levied charges that share that due date. Unbilled interest is absent.
    charges = sum(
        charge.ex_vat_cents + charge.vat_cents
        for charge in account.charges
        if charge.due_on == chosen.due_on and charge.bucket != "additional_monthly"
    )
    return chosen.amount_cents + charges, chosen.due_on


def _signed(lines: tuple[TransactionView, ...], *, kind: str) -> int:
    return sum(line.credit_cents - line.debit_cents for line in lines if line.kind == kind and line.bucket in _OWING_BUCKETS)


def _bucket_movement(lines: tuple[TransactionView, ...], bucket: str) -> int:
    return sum(line.debit_cents - line.credit_cents for line in lines if line.bucket == bucket)


def _covers_month_end(start: date, end: date) -> bool:
    day = start
    while day <= end:
        if day == month_end(day):
            return True
        day += timedelta(days=1)
    return False


def _service_fee_cents(record: AgreementRecord) -> int:
    for instrument in record.product.instruments:
        for fee in instrument.fees:
            if fee.code == "service":
                return fee.amount_cents
    return 0


def _engine_agreement(record: AgreementRecord, account: LoanAccount) -> Agreement:
    product = Product.MICRO if account.snapshot.classification == "short_term" else Product.PERSONAL
    return Agreement(
        product=product,
        credit_provider_org_id=record.organisation_id,
        consumer_party_id=record.person_id,
        product_enrolment_id=record.enrolment_id,
        cash_advanced_cents=record.cash_advanced_cents,
        advance_date=account.disbursement_value_date,
        maturity_date=account.contractual_end,
        agreed_monthly_rate=account.snapshot.base_rate if product == Product.MICRO else None,
        margin_annual=account.snapshot.base_rate if product == Product.PERSONAL else Decimal("0.21"),
        principal_instalments=_quote_instalments(record, account),
        campaign_interest_discount=account.snapshot.discount_rate,
        initiation_capitalised=account.snapshot.initiation_capitalised,
        booked_initiation_ex_vat_cents=record.initiation_fee_cents,
    )


def _quote_instalments(record: AgreementRecord, account: LoanAccount) -> tuple[tuple[date, int], ...]:
    """Principal slices the quote may capitalise onto.

    A capitalised initiation fee is already inside the booked loan value.
    Those slices are reduced by the booked ex-VAT fee so the quote adds
    that fee once, with VAT, and does not add it again.
    """
    lines = tuple(sorted((slice_.due_on, slice_.amount_cents) for slice_ in account.slices))
    if not account.snapshot.initiation_capitalised or record.initiation_fee_cents == 0:
        return lines
    remaining = record.initiation_fee_cents
    adjusted: list[tuple[date, int]] = []
    for index, (due, amount) in enumerate(lines):
        last = index == len(lines) - 1
        room = amount if last else max(amount - 1, 0)
        take = min(remaining, room)
        if amount - take <= 0:
            raise DocumentsError(
                "initiation",
                "The capitalised initiation fee is already in the loan value, "
                "and removing it would drop a principal instalment.",
            )
        adjusted.append((due, amount - take))
        remaining -= take
    if remaining != 0 or sum(amount for _, amount in adjusted) != record.cash_advanced_cents:
        raise DocumentsError(
            "initiation",
            "The loan principal does not equal the cash advanced plus the capitalised initiation fee.",
        )
    return tuple(adjusted)


def _policy(account: LoanAccount, service_fee_monthly_cents: int) -> Policy:
    snapshot = account.snapshot
    basis = FeeCapBasis.EXCLUSIVE if snapshot.vat_on_rand_maxima == "exclusive" else FeeCapBasis.INCLUSIVE
    code = snapshot.day_count_code or ""
    if code not in {DAY_COUNT_ACTUAL_ACTUAL, DAY_COUNT_30_360}:
        raise DocumentsError("election-unset", "Day count is unset. LOCKED_DECISIONS §5.")
    return Policy(
        fee_cap_basis=basis,
        day_count=_day_count(code),
        interest_on_deferred_initiation=snapshot.interest_on_deferred_initiation == "permitted",
        service_fee_monthly_cents=service_fee_monthly_cents,
        leniency_days=snapshot.leniency_days,
        full_payment_threshold_percent=snapshot.full_payment_threshold_percent,
        repo_fall=_repo_fall(snapshot.repo_rate_fall),
        prepayment_choice=_prepayment(snapshot.partial_prepayment),
        terminal_service_fee=TerminalServiceFee.FULL,
    )


def _payment_events(ledger: Ledger, account: LoanAccount) -> tuple[Payment, ...]:
    events: list[Payment] = []
    for transaction in ledger.store.transactions_for(account.organisation_id, account.loan_id):
        if transaction.kind != "payment" or not transaction.amount_cents:
            continue
        events.append(
            Payment(
                transaction.value_date,
                transaction.amount_cents,
                sequence=transaction.recognition_sequence,
            )
        )
    return tuple(events)


def _anniversary(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _from_ledger(exc: LedgerError) -> DocumentsError:
    return DocumentsError(exc.code, str(exc))
