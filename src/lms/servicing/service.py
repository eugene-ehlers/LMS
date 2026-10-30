"""Servicing workflows.

This module does not calculate interest, allocate a receipt, or post a
journal. Those calls go to ``lms.calc``, ``lms_config``, and ``lms.ledger``.

LOCKED_DECISIONS.md (28 October 2026) is the source of truth. A gap is
raised in ``docs/servicing/implementation-note.md`` and is not given a value.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from lms.calc.fees import initiation_cap_ex_vat_cents
from lms.calc.interest import nominal_annual_rate, periods_per_year
from lms.calc.ledger import run
from lms.calc.models import Agreement, FeeCapBasis, Policy, Product, RepoRate
from lms.calc.money import RuleError
from lms.laybye.errors import LaybyeError
from lms.laybye.service import grant_loan, prepare_pair, receive_pre_disbursement
from lms.ledger.errors import LedgerError
from lms.rate_fee_change.errors import RateFeeChangeError
from lms.rate_fee_change.service import RateFeeChanges
from lms.ledger.models import LoanAccount
from lms.ledger.service import Ledger, _day_count, _prepayment, _repo_fall
from lms.regulatory.audit import AuditLog
from lms.servicing.enigma import EnigmaStub
from lms.servicing.errors import ServicingError
from lms_config.calendar import value_date, value_instant
from lms_config.exceptions import CalculationInputError
from lms_config.locked import (
    OrganisationSettings,
    ResolvedCreditSettings,
    require_booking_in_duplum_trigger,
    resolve_customer_settings,
)
from lms_config.validate import SHORT_TERM, UNSECURED, ProductTerms, validate_terms

_CREDIT = {SHORT_TERM, UNSECURED}
_ALLOCATABLE = {"active", "in_arrears"}
_ENGINE_PRODUCT = {SHORT_TERM: Product.MICRO, UNSECURED: Product.PERSONAL}


@dataclass
class AgreementRecord:
    agreement_id: str
    organisation_id: str
    person_id: str
    product: ProductTerms
    settings: OrganisationSettings
    resolved: ResolvedCreditSettings
    recognised_at: datetime
    booking_value_date: date
    cash_advanced_cents: int
    frequency: str
    schedule: tuple[tuple[date, int], ...]
    initiation_fee_cents: int
    quoted_disbursement: date | None
    enrolment_id: str
    frozen_full_name: str
    frozen_id_number: str
    frozen_service_address: str
    annual_equivalent_rate: Decimal | None
    status: str = "pending_disbursement"
    ledger_loan_id: str | None = None
    laybye_loan_id: str | None = None
    disbursement_value_date: date | None = None


@dataclass
class PaymentRecord:
    payment_id: str
    organisation_id: str
    person_id: str
    cents: int
    recognised_at: datetime
    value_date: date
    status: str
    agreement_id: str | None = None
    attributed_due_on: date | None = None
    ledger_transaction_id: str | None = None
    allocations: tuple[tuple[str, int], ...] = ()
    reversal_value_date: date | None = None
    reversal_recognised_at: datetime | None = None
    reversal_transaction_id: str | None = None


@dataclass(frozen=True)
class IssuedStatement:
    statement_id: str
    organisation_id: str
    person_id: str
    period_start: date
    period_end: date
    loans: tuple[dict, ...]
    pdf_sha256: str
    pdf_stub: bytes


@dataclass
class Servicing:
    ledger: Ledger = field(default_factory=Ledger)
    enigma: EnigmaStub = field(default_factory=EnigmaStub)
    agreements: dict[str, AgreementRecord] = field(default_factory=dict)
    payments: dict[str, PaymentRecord] = field(default_factory=dict)
    statements: dict[tuple[str, str, date, date], IssuedStatement] = field(default_factory=dict)
    audit: AuditLog = field(default_factory=AuditLog)
    rate_fee_changes: RateFeeChanges | None = None
    _idempotency: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)

    def book(
        self,
        *,
        organisation_id: str,
        person_id: str,
        product: ProductTerms,
        settings: OrganisationSettings,
        recognised_at: datetime,
        cash_advanced_cents: int,
        frequency: str,
        schedule: tuple[tuple[date, int], ...],
        initiation_fee_cents: int = 0,
        quoted_disbursement: date | None = None,
        idempotency_key: str,
        repos: tuple[RepoRate, ...] = (),
    ) -> AgreementRecord:
        """POST /v1/agreements. Freeze elections. Do not post to the ledger."""
        fingerprint = _fingerprint(
            {
                "organisation_id": organisation_id,
                "person_id": person_id,
                "cash_advanced_cents": cash_advanced_cents,
                "frequency": frequency,
                "schedule": [(due.isoformat(), amount) for due, amount in schedule],
                "initiation_fee_cents": initiation_fee_cents,
                "quoted_disbursement": quoted_disbursement.isoformat() if quoted_disbursement else None,
                "recognised_at": recognised_at.isoformat(),
                "classification": product.classification,
            }
        )
        replay = self._replay("book", organisation_id, idempotency_key, fingerprint)
        if replay is not None:
            return self.agreements[replay]
        identity = self.enigma.check(organisation_id, person_id, "agreement.book")
        resolved = self._resolve(settings, product)
        self._engine_validate(
            organisation_id=organisation_id,
            person_id=person_id,
            enrolment_id=identity.enrolment_id,
            product=product,
            resolved=resolved,
            cash_advanced_cents=cash_advanced_cents,
            schedule=schedule,
            initiation_fee_cents=initiation_fee_cents,
            advance=quoted_disbursement or value_date(recognised_at),
            repos=repos,
            agreement_id=None,
        )
        disclosure = _annual_equivalent(product, resolved)
        record = AgreementRecord(
            agreement_id=str(uuid4()),
            organisation_id=organisation_id,
            person_id=person_id,
            product=product,
            settings=settings,
            resolved=resolved,
            recognised_at=recognised_at,
            booking_value_date=value_date(recognised_at),
            cash_advanced_cents=cash_advanced_cents,
            frequency=frequency,
            schedule=tuple(schedule),
            initiation_fee_cents=initiation_fee_cents,
            quoted_disbursement=quoted_disbursement,
            enrolment_id=identity.enrolment_id,
            frozen_full_name=identity.full_name,
            frozen_id_number=identity.id_number,
            frozen_service_address=identity.service_address,
            annual_equivalent_rate=disclosure,
        )
        self.agreements[record.agreement_id] = record
        self._remember("book", organisation_id, idempotency_key, fingerprint, record.agreement_id)
        self._audit(
            organisation_id=organisation_id,
            occurred_at=recognised_at,
            event_type="AGREEMENT_STATUS_CHANGED",
            category="operational",
            agreement_id=record.agreement_id,
            enigma_person_id=person_id,
            payload={"status": record.status},
        )
        return record

    def book_linked_laybye(
        self,
        *,
        organisation_id: str,
        person_id: str,
        product: ProductTerms,
        settings: OrganisationSettings,
        recognised_at: datetime,
        cash_advanced_cents: int,
        frequency: str,
        schedule: tuple[tuple[date, int], ...],
        initiation_fee_cents: int = 0,
        quoted_disbursement: date | None = None,
        idempotency_key: str,
        repos: tuple[RepoRate, ...] = (),
        pre_disbursement_cents: int | None = None,
        pre_disbursement_at: datetime | None = None,
        grant_at: datetime | None = None,
    ) -> AgreementRecord:
        """Book a linked Laybye, take a pre-disbursement receipt, then grant.

        The receipt is cash in on the Laybye child. Parent principal stays
        at zero until ``grant_at`` is set, or until a later ``disburse``.
        LOCKED_DECISIONS §4. A replay of the same book key does not prepare
        a second pair or post a second deposit.
        """
        record = self.book(
            organisation_id=organisation_id,
            person_id=person_id,
            product=product,
            settings=settings,
            recognised_at=recognised_at,
            cash_advanced_cents=cash_advanced_cents,
            frequency=frequency,
            schedule=schedule,
            initiation_fee_cents=initiation_fee_cents,
            quoted_disbursement=quoted_disbursement,
            idempotency_key=idempotency_key,
            repos=repos,
        )
        if record.ledger_loan_id is None:
            try:
                parent, child = prepare_pair(
                    self.ledger,
                    organisation_id=record.organisation_id,
                    person_id=record.person_id,
                    product=record.product,
                    organisation=record.settings,
                    recognised_at=record.recognised_at,
                    cash_advanced_cents=record.cash_advanced_cents,
                    frequency=record.frequency,
                    schedule=record.schedule,
                    identity_name=record.frozen_full_name,
                    identity_number=record.frozen_id_number,
                    service_address=record.frozen_service_address,
                    quoted_disbursement=record.quoted_disbursement,
                    initiation_fee_cents=record.initiation_fee_cents,
                    contractual_end=max(due for due, _amount in record.schedule),
                )
            except (LedgerError, LaybyeError, CalculationInputError, RuleError) as exc:
                raise _from_downstream(exc) from exc
            record.ledger_loan_id = parent.loan_id
            record.laybye_loan_id = child.loan_id
        if pre_disbursement_cents is not None:
            if pre_disbursement_at is None:
                raise ServicingError(
                    "pre-disbursement",
                    "A pre-disbursement receipt needs a recognition time.",
                )
            if record.laybye_loan_id is None:
                raise ServicingError(
                    "laybye-missing",
                    "LOCKED_DECISIONS §4: a pre-disbursement receipt sits in the Laybye only "
                    "when a Laybye account exists.",
                )
            existing = [
                transaction
                for transaction in self.ledger.store.transactions_for(
                    record.organisation_id, record.laybye_loan_id
                )
                if transaction.kind == "laybye_deposit"
            ]
            posted = sum(transaction.amount_cents for transaction in existing)
            if existing and posted != pre_disbursement_cents:
                raise ServicingError(
                    "idempotency",
                    "A different pre-disbursement receipt is already posted.",
                )
            if not existing and record.disbursement_value_date is not None:
                raise ServicingError(
                    "already-granted",
                    "LOCKED_DECISIONS §4: once the loan is granted, payments go to the loan first.",
                )
            if not existing:
                try:
                    deposit = receive_pre_disbursement(
                        self.ledger,
                        organisation_id=record.organisation_id,
                        parent_loan_id=record.ledger_loan_id,
                        cents=pre_disbursement_cents,
                        recognised_at=pre_disbursement_at,
                    )
                except (LedgerError, LaybyeError, CalculationInputError, RuleError) as exc:
                    raise _from_downstream(exc) from exc
                self._audit(
                    organisation_id=record.organisation_id,
                    occurred_at=pre_disbursement_at,
                    event_type="DEPOSIT_RECEIVED",
                    category="financial",
                    amount_cents=pre_disbursement_cents,
                    balance_code="deposit",
                    agreement_id=record.agreement_id,
                    enigma_person_id=record.person_id,
                    payload={
                        "loan_id": record.laybye_loan_id,
                        "transaction_id": deposit.transaction_id,
                    },
                )
        if grant_at is not None:
            return self.disburse(record.agreement_id, recognised_at=grant_at, repos=repos)
        return record

    def disburse(
        self,
        agreement_id: str,
        *,
        recognised_at: datetime,
        repos: tuple[RepoRate, ...] = (),
    ) -> AgreementRecord:
        """POST /v1/agreements/{id}/disbursements. Posts through the ledger."""
        record = self._agreement(agreement_id)
        if record.disbursement_value_date is not None:
            return record
        if record.status != "pending_disbursement":
            raise ServicingError("status", f"Cannot disburse an agreement in {record.status}.")
        self.enigma.check(record.organisation_id, record.person_id, "disbursement.confirm")
        advance = value_date(recognised_at)
        self._engine_validate(
            organisation_id=record.organisation_id,
            person_id=record.person_id,
            enrolment_id=record.enrolment_id,
            product=record.product,
            resolved=record.resolved,
            cash_advanced_cents=record.cash_advanced_cents,
            schedule=record.schedule,
            initiation_fee_cents=record.initiation_fee_cents,
            advance=advance,
            repos=repos,
            agreement_id=record.agreement_id,
        )
        try:
            if record.ledger_loan_id is not None:
                account = grant_loan(
                    self.ledger,
                    organisation_id=record.organisation_id,
                    parent_loan_id=record.ledger_loan_id,
                    recognised_at=recognised_at,
                    schedule=record.schedule,
                    initiation_fee_cents=record.initiation_fee_cents,
                )
            else:
                account = self.ledger.book(
                    organisation_id=record.organisation_id,
                    person_id=record.person_id,
                    product=record.product,
                    organisation=record.settings,
                    recognised_at=recognised_at,
                    cash_advanced_cents=record.cash_advanced_cents,
                    frequency=record.frequency,
                    schedule=record.schedule,
                    identity_name=record.frozen_full_name,
                    identity_number=record.frozen_id_number,
                    service_address=record.frozen_service_address,
                    quoted_disbursement=record.quoted_disbursement,
                    initiation_fee_cents=record.initiation_fee_cents,
                    contractual_end=max(due for due, _amount in record.schedule),
                )
        except (LedgerError, LaybyeError, CalculationInputError, RuleError) as exc:
            raise _from_downstream(exc) from exc
        record.ledger_loan_id = account.loan_id
        record.disbursement_value_date = account.disbursement_value_date
        record.status = "active"
        self._audit(
            organisation_id=record.organisation_id,
            occurred_at=recognised_at,
            event_type="PRINCIPAL_ADVANCED",
            category="financial",
            amount_cents=record.cash_advanced_cents,
            balance_code="principal",
            agreement_id=record.agreement_id,
            enigma_person_id=record.person_id,
            payload={"loan_id": account.loan_id},
        )
        return record

    def accept_payment(
        self,
        *,
        organisation_id: str,
        person_id: str,
        cents: int,
        recognised_at: datetime,
        idempotency_key: str,
        agreement_id: str | None = None,
        attributed_due_on: date | None = None,
    ) -> PaymentRecord:
        """POST /v1/payments. Unmatched receipts stay out of the loan ledger."""
        fingerprint = _fingerprint(
            {
                "organisation_id": organisation_id,
                "person_id": person_id,
                "cents": cents,
                "recognised_at": recognised_at.isoformat(),
                "agreement_id": agreement_id,
                "attributed_due_on": attributed_due_on.isoformat() if attributed_due_on else None,
            }
        )
        replay = self._replay("payment", organisation_id, idempotency_key, fingerprint)
        if replay is not None:
            return self.payments[replay]
        self.enigma.check(organisation_id, person_id, "payment.accept")
        if cents < 0:
            raise ServicingError("payment", "A receipt cannot be negative.")
        record = PaymentRecord(
            payment_id=str(uuid4()),
            organisation_id=organisation_id,
            person_id=person_id,
            cents=cents,
            recognised_at=recognised_at,
            value_date=value_date(recognised_at),
            status="unapplied",
        )
        matched = self._match(organisation_id, person_id, agreement_id)
        if matched is None:
            self.payments[record.payment_id] = record
            self._remember("payment", organisation_id, idempotency_key, fingerprint, record.payment_id)
            return record
        self._allocate(record, matched, attributed_due_on)
        self.payments[record.payment_id] = record
        self._remember("payment", organisation_id, idempotency_key, fingerprint, record.payment_id)
        return record

    def apply_payment(
        self,
        payment_id: str,
        *,
        agreement_id: str,
        attributed_due_on: date,
    ) -> PaymentRecord:
        """Match a suspense receipt. The value date stays the original recognition date."""
        payment = self._payment(payment_id)
        if payment.status == "allocated" and payment.agreement_id == agreement_id:
            return payment
        if payment.status != "unapplied":
            raise ServicingError("payment", f"Cannot allocate a payment in {payment.status}.")
        matched = self._match(payment.organisation_id, payment.person_id, agreement_id)
        if matched is None:
            raise ServicingError(
                "unmatched",
                "The agreement was not found for this organisation and person. The receipt stays unapplied.",
            )
        self._allocate(payment, matched, attributed_due_on)
        return payment

    def reverse_payment(self, payment_id: str, *, recognised_at: datetime) -> PaymentRecord:
        """POST /v1/payments/{id}/reversals. The ledger keeps the original value date."""
        payment = self._payment(payment_id)
        if payment.status == "reversed":
            return payment
        self.enigma.check(payment.organisation_id, payment.person_id, "payment.reverse")
        if payment.status == "unapplied":
            payment.status = "reversed"
            payment.reversal_value_date = payment.value_date
            payment.reversal_recognised_at = recognised_at
            return payment
        if payment.ledger_transaction_id is None or payment.agreement_id is None:
            raise ServicingError("payment", "An allocated payment has no ledger transaction.")
        agreement = self._agreement(payment.agreement_id)
        try:
            reversal = self.ledger.reverse(
                organisation_id=payment.organisation_id,
                transaction_id=payment.ledger_transaction_id,
                recognised_at=recognised_at,
            )
        except LedgerError as exc:
            raise _from_downstream(exc) from exc
        if reversal.value_date != payment.value_date:
            raise ServicingError(
                "value-date",
                "LOCKED_DECISIONS §1: a reversal must use the value date originally recognised.",
            )
        payment.status = "reversed"
        payment.reversal_value_date = reversal.value_date
        payment.reversal_recognised_at = reversal.recognised_at
        payment.reversal_transaction_id = reversal.transaction_id
        self._refresh_status(agreement)
        return payment

    def morning_check(
        self,
        agreement_id: str,
        *,
        due_on: date,
        recognised_at: datetime,
    ) -> AgreementRecord:
        """Flag or cure default. The instalment is assembled from §6, not from an example."""
        record = self._agreement(agreement_id)
        if record.status not in _ALLOCATABLE or record.ledger_loan_id is None:
            raise ServicingError("status", f"No morning check for {record.status}.")
        account = self._loan(record)
        instalment = _threshold_instalment(account, due_on)
        try:
            self.ledger.flag_default(
                organisation_id=record.organisation_id,
                loan_id=record.ledger_loan_id,
                check_on=value_date(recognised_at),
                due_on=due_on,
                instalment_cents=instalment,
                recognised_at=recognised_at,
            )
        except LedgerError as exc:
            raise _from_downstream(exc) from exc
        self._refresh_status(record)
        return record

    def issue_statement(
        self,
        *,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
        vat_rate: Decimal | None = None,
        interest_cap_present: bool,
    ) -> IssuedStatement:
        """One statement per person per organisation. PDF bytes are a stub."""
        self.enigma.check(organisation_id, person_id, "statement.issue")
        if period_end < period_start:
            raise ServicingError("statement-period", "The statement period ends before it starts.")
        key = (organisation_id, person_id, period_start, period_end)
        existing = self.statements.get(key)
        if existing is not None:
            return existing
        loans = [
            record
            for record in self.agreements.values()
            if record.organisation_id == organisation_id
            and record.person_id == person_id
            and record.ledger_loan_id is not None
            and record.status in {"active", "in_arrears", "settled"}
        ]
        for record in loans:
            self._accrue_and_bill(record, period_start, period_end, vat_rate, interest_cap_present)
        try:
            statement = self.ledger.issue_statement(
                organisation_id=organisation_id,
                person_id=person_id,
                period_start=period_start,
                period_end=period_end,
            )
        except LedgerError as exc:
            raise _from_downstream(exc) from exc
        rows = tuple(
            {
                "loan_id": line.loan_id,
                "opening": dict(line.opening),
                "closing": dict(line.closing),
                "frozen_full_name": self._frozen_name(line.loan_id),
            }
            for line in statement.loans
        )
        payload = json.dumps(
            {
                "organisation_id": organisation_id,
                "person_id": person_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "loans": rows,
            },
            sort_keys=True,
        ).encode()
        issued = IssuedStatement(
            statement_id=str(uuid4()),
            organisation_id=organisation_id,
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
            loans=rows,
            pdf_sha256=hashlib.sha256(payload).hexdigest(),
            pdf_stub=payload,
        )
        self.statements[key] = issued
        self._audit(
            organisation_id=organisation_id,
            occurred_at=value_instant(period_end),
            event_type="STATEMENT_ISSUED",
            category="operational",
            agreement_id=None,
            enigma_person_id=person_id,
            payload={
                "statement_id": issued.statement_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        return issued

    def _resolve(self, settings: OrganisationSettings, product: ProductTerms) -> ResolvedCreditSettings:
        try:
            validate_terms(product)
            resolved = resolve_customer_settings(settings, product)
            require_booking_in_duplum_trigger(resolved.in_duplum_trigger)
            return resolved
        except CalculationInputError as exc:
            raise ServicingError("election-unset", str(exc)) from exc

    def _engine_validate(
        self,
        *,
        organisation_id: str,
        person_id: str,
        enrolment_id: str,
        product: ProductTerms,
        resolved: ResolvedCreditSettings,
        cash_advanced_cents: int,
        schedule: tuple[tuple[date, int], ...],
        initiation_fee_cents: int,
        advance: date,
        repos: tuple[RepoRate, ...],
        agreement_id: str | None,
    ) -> None:
        """Call the calculation engine. Do not copy its amounts onto the ledger."""
        if product.classification not in _CREDIT:
            return
        if initiation_fee_cents < 0:
            raise ServicingError("initiation", "Initiation fee cannot be negative.")
        try:
            cap = initiation_cap_ex_vat_cents(cash_advanced_cents)
        except RuleError as exc:
            raise ServicingError(exc.code, str(exc)) from exc
        if initiation_fee_cents > cap:
            raise ServicingError(
                "initiation-cap",
                "The initiation fee is above the cap returned by the calculation engine.",
            )
        engine_product = _ENGINE_PRODUCT[product.classification]
        priors = self._prior_inceptions(organisation_id, person_id, advance, agreement_id)
        try:
            agreement = Agreement(
                product=engine_product,
                credit_provider_org_id=organisation_id,
                consumer_party_id=person_id,
                product_enrolment_id=enrolment_id,
                cash_advanced_cents=cash_advanced_cents,
                advance_date=advance,
                maturity_date=max(due for due, _ in schedule),
                agreed_monthly_rate=resolved.base_rate if engine_product == Product.MICRO else None,
                margin_annual=resolved.base_rate if engine_product == Product.PERSONAL else Decimal("0.21"),
                prior_short_term_inceptions=priors,
                principal_instalments=schedule,
                campaign_interest_discount=resolved.discount_rate,
                initiation_capitalised=product.initiation_capitalised,
                booked_initiation_ex_vat_cents=initiation_fee_cents,
            )
            policy = _policy(resolved, _service_fee_cents(product))
            if engine_product == Product.PERSONAL and not repos:
                raise ServicingError(
                    "repo-unset",
                    "LOCKED_DECISIONS §11: an unsecured accrual needs a repo rate. None was supplied, and none is assumed.",
                )
            run(agreement, until=advance, policy=policy, repos=repos)
        except (RuleError, CalculationInputError, LedgerError) as exc:
            raise ServicingError(getattr(exc, "code", "engine-rejected"), str(exc)) from exc

    def _prior_inceptions(
        self,
        organisation_id: str,
        person_id: str,
        advance: date,
        agreement_id: str | None,
    ) -> tuple[date, ...]:
        found: list[date] = []
        for record in self.agreements.values():
            if record.agreement_id == agreement_id:
                continue
            if record.organisation_id != organisation_id or record.person_id != person_id:
                continue
            if record.product.classification != SHORT_TERM or record.disbursement_value_date is None:
                continue
            if record.disbursement_value_date.year == advance.year and record.disbursement_value_date <= advance:
                found.append(record.disbursement_value_date)
        return tuple(found)

    def _audit(self, **kwargs) -> None:
        """Append one row to ``Servicing.audit``.

        This is the in-process hook. A database caller inserts
        ``lms.audit_event`` instead. ``lms.seal_audit_event`` fills the
        hash chain on that insert. Direct ledger posts are not sealed
        unless the caller appends.
        """
        self.audit.append(**kwargs)

    def _audit_payment(self, payment: PaymentRecord, transaction, laybye_id: str | None) -> None:
        if transaction.kind == "laybye_deposit":
            self._audit(
                organisation_id=payment.organisation_id,
                occurred_at=payment.recognised_at,
                event_type="DEPOSIT_RECEIVED",
                category="financial",
                amount_cents=transaction.amount_cents,
                balance_code="deposit",
                agreement_id=payment.agreement_id,
                enigma_person_id=payment.person_id,
                payload={"transaction_id": transaction.transaction_id},
            )
            return
        self._audit(
            organisation_id=payment.organisation_id,
            occurred_at=payment.recognised_at,
            event_type="PAYMENT_ALLOCATED",
            category="financial",
            amount_cents=transaction.amount_cents,
            agreement_id=payment.agreement_id,
            enigma_person_id=payment.person_id,
            payload={
                "transaction_id": transaction.transaction_id,
                "allocations": [[bucket, amount] for bucket, amount in payment.allocations],
            },
        )
        if laybye_id is None:
            return
        laybye_tx = self.ledger.store.get_transaction(payment.organisation_id, laybye_id)
        self._audit(
            organisation_id=payment.organisation_id,
            occurred_at=payment.recognised_at,
            event_type="DEPOSIT_RECEIVED",
            category="financial",
            amount_cents=laybye_tx.amount_cents,
            balance_code="deposit",
            agreement_id=payment.agreement_id,
            enigma_person_id=payment.person_id,
            payload={"transaction_id": laybye_tx.transaction_id},
        )

    def _allocate(self, payment: PaymentRecord, agreement: AgreementRecord, attributed_due_on: date | None) -> None:
        if agreement.status not in _ALLOCATABLE or agreement.ledger_loan_id is None:
            raise ServicingError("status", f"Cannot allocate to an agreement in {agreement.status}.")
        if attributed_due_on is None:
            raise ServicingError(
                "due-date-attribution-unset",
                "LOCKED_DECISIONS §6 compares the amount received for a due date. "
                "Section 8 does not attribute a receipt, so a matched payment without a due date fails closed.",
            )
        try:
            transaction = self.ledger.post_payment(
                organisation_id=payment.organisation_id,
                loan_id=agreement.ledger_loan_id,
                cents=payment.cents,
                recognised_at=payment.recognised_at,
                attributed_due_on=attributed_due_on,
            )
        except LedgerError as exc:
            raise _from_downstream(exc) from exc
        if transaction.value_date != payment.value_date:
            raise ServicingError(
                "value-date",
                "LOCKED_DECISIONS §1: the ledger value date must be the system recognition date.",
            )
        payment.agreement_id = agreement.agreement_id
        payment.attributed_due_on = attributed_due_on
        payment.ledger_transaction_id = transaction.transaction_id
        payment.allocations = tuple(
            (entry.bucket, entry.credit_cents)
            for entry in transaction.entries
            if entry.bucket is not None and entry.credit_cents
        )
        laybye_id = self.ledger._last_laybye_transaction_id
        if laybye_id is not None and transaction.kind == "payment":
            laybye_tx = self.ledger.store.get_transaction(payment.organisation_id, laybye_id)
            payment.allocations = payment.allocations + (("laybye_hold", laybye_tx.amount_cents),)
        payment.status = "allocated"
        self._audit_payment(payment, transaction, laybye_id)
        self._refresh_status(agreement)

    def _accrue_and_bill(
        self,
        record: AgreementRecord,
        period_start: date,
        period_end: date,
        vat_rate: Decimal | None,
        interest_cap_present: bool,
    ) -> None:
        account = self._loan(record)
        start = max(period_start, account.disbursement_value_date)
        end = min(period_end, account.contractual_end)
        if start > end:
            return
        day = start
        while day <= end:
            override = None
            if self.rate_fee_changes is not None:
                override = self.rate_fee_changes.periodic_rate_override(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(day),
                )
            try:
                self.ledger.accrue_day(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(day),
                    interest_cap_present=interest_cap_present,
                    periodic_rate_override=override,
                )
            except (LedgerError, RateFeeChangeError) as exc:
                if getattr(exc, "code", "") not in {"already-accrued", "outside-term"}:
                    raise _from_downstream(exc) from exc
            day += timedelta(days=1)
        try:
            self.ledger.bill_interest(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(end),
            )
        except LedgerError as exc:
            raise _from_downstream(exc) from exc
        monthly = _service_fee_cents(record.product)
        if monthly == 0:
            return
        if vat_rate is None:
            raise ServicingError(
                "vat-rate-unset",
                "LOCKED_DECISIONS §9 does not store a VAT rate. The statement fails closed until the caller supplies one.",
            )
        first_due = min(due for due, _ in record.schedule)
        month_cursor = date(start.year, start.month, 1)
        while month_cursor <= end:
            levy_day = start if (month_cursor.year, month_cursor.month) == (start.year, start.month) else month_cursor
            if levy_day < start:
                levy_day = start
            if levy_day > end:
                break
            opening = (
                levy_day.year == account.disbursement_value_date.year
                and levy_day.month == account.disbursement_value_date.month
                and first_due > account.disbursement_value_date
            )
            amount = monthly
            due_on = first_due if opening else levy_day
            if self.rate_fee_changes is not None:
                amount = self.rate_fee_changes.service_fee_for_levy(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(levy_day),
                    monthly_cents=monthly,
                )
                due_on = self.rate_fee_changes.fee_due_on(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(levy_day),
                    contractual_due_on=due_on,
                )
            try:
                self.ledger.levy_service_fee(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(levy_day),
                    monthly_cents=amount,
                    due_on=due_on,
                    interest_cap_present=interest_cap_present,
                    vat_rate=vat_rate,
                    opening=opening,
                    first_due=first_due if opening else None,
                )
            except (LedgerError, RateFeeChangeError) as exc:
                if getattr(exc, "code", "") != "service-fee-once":
                    raise _from_downstream(exc) from exc
            if month_cursor.month == 12:
                month_cursor = date(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)

    def _refresh_status(self, record: AgreementRecord) -> None:
        if record.ledger_loan_id is None:
            return
        account = self._loan(record)
        if _cleared(self.ledger, account):
            record.status = "settled"
            return
        open_episode = next((episode for episode in account.episodes if episode.closed_on is None), None)
        record.status = "in_arrears" if open_episode is not None else "active"

    def _match(self, organisation_id: str, person_id: str, agreement_id: str | None) -> AgreementRecord | None:
        if agreement_id is None:
            return None
        record = self.agreements.get(agreement_id)
        if record is None:
            return None
        if record.organisation_id != organisation_id or record.person_id != person_id:
            raise ServicingError(
                "enigma-ambiguous",
                "LOCKED_DECISIONS §15: the agreement does not belong to this organisation and person. The receipt is not allocated.",
            )
        return record

    def _agreement(self, agreement_id: str) -> AgreementRecord:
        record = self.agreements.get(agreement_id)
        if record is None:
            raise ServicingError("not-found", "No agreement with that id.", status=404)
        return record

    def _payment(self, payment_id: str) -> PaymentRecord:
        payment = self.payments.get(payment_id)
        if payment is None:
            raise ServicingError("not-found", "No payment with that id.", status=404)
        return payment

    def _loan(self, record: AgreementRecord) -> LoanAccount:
        if record.ledger_loan_id is None:
            raise ServicingError("status", "The agreement has not been disbursed.")
        return self.ledger.store.get(record.organisation_id, record.ledger_loan_id)

    def _frozen_name(self, loan_id: str) -> str:
        for record in self.agreements.values():
            if record.ledger_loan_id == loan_id:
                return record.frozen_full_name
        return ""

    def _replay(self, kind: str, organisation_id: str, key: str, fingerprint: str) -> str | None:
        if not key:
            raise ServicingError("idempotency-required", "Booking and payment require an idempotency key.")
        stored = self._idempotency.get((kind, organisation_id, key))
        if stored is None:
            return None
        previous, resource_id = stored
        if previous != fingerprint:
            raise ServicingError(
                "idempotency-conflict",
                "This idempotency key was already used for a different request.",
                status=409,
            )
        return resource_id

    def _remember(self, kind: str, organisation_id: str, key: str, fingerprint: str, resource_id: str) -> None:
        self._idempotency[(kind, organisation_id, key)] = (fingerprint, resource_id)


def _policy(resolved: ResolvedCreditSettings, service_fee_monthly_cents: int) -> Policy:
    basis = FeeCapBasis.EXCLUSIVE if resolved.vat_on_rand_maxima == "exclusive" else FeeCapBasis.INCLUSIVE
    day_count = _day_count(resolved.day_count_code or "")
    return Policy(
        fee_cap_basis=basis,
        day_count=day_count,
        interest_on_deferred_initiation=resolved.interest_on_deferred_initiation == "permitted",
        service_fee_monthly_cents=service_fee_monthly_cents,
        leniency_days=resolved.leniency_days,
        full_payment_threshold_percent=resolved.full_payment_threshold_percent,
        repo_fall=_repo_fall(resolved.repo_rate_fall),
        prepayment_choice=_prepayment(resolved.partial_prepayment),
    )


def _annual_equivalent(product: ProductTerms, resolved: ResolvedCreditSettings) -> Decimal | None:
    engine_product = _ENGINE_PRODUCT.get(product.classification)
    if engine_product is None:
        return None
    try:
        return nominal_annual_rate(resolved.base_rate, periods_per_year(engine_product))
    except RuleError as exc:
        raise ServicingError(exc.code, str(exc)) from exc


def _service_fee_cents(product: ProductTerms) -> int:
    for instrument in product.instruments:
        for fee in instrument.fees:
            if fee.code == "service":
                return fee.amount_cents
    return 0


def _threshold_instalment(account: LoanAccount, due_on: date) -> int:
    """LOCKED_DECISIONS §6. Unbilled interest is not a charge, so it is absent here."""
    principal = sum(slice_.amount_cents for slice_ in account.slices if slice_.due_on == due_on)
    levied = sum(
        charge.ex_vat_cents + charge.vat_cents
        for charge in account.charges
        if charge.due_on == due_on and charge.bucket != "additional_monthly"
    )
    return principal + levied


def _cleared(ledger: Ledger, account: LoanAccount) -> bool:
    if any(slice_.remaining_cents for slice_ in account.slices):
        return False
    if any(charge.remaining_cents for charge in account.charges):
        return False
    return ledger.bucket_balance(account, "principal") == 0


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _from_downstream(exc: Exception) -> ServicingError:
    code = getattr(exc, "code", "downstream")
    return ServicingError(code, str(exc))
