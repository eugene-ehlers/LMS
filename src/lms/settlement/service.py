"""Settle one agreement and book the loan the decision engine has already priced.

Capitalise due amounts, then allocate the receipt in section 126 order. The
agreement is marked settled only when that balance is 0 cents. The new rate,
term, instalment, and 5% / 3% flag are stored as supplied. This module does
not decide concurrent, subsequent, or restructure treatment.

A restructure of the same agreement, and an early settlement with no new loan,
are refused. Collection campaigns are not applied.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

from lms.calc.models import Agreement, Product, RepoRate
from lms.calc.money import RuleError
from lms.ledger.errors import LedgerError
from lms.ledger.models import FREQUENCIES
from lms.payments.errors import PaymentRailError
from lms.payments.loan_numbers import LoanNumberSeries
from lms.servicing.errors import ServicingError
from lms.servicing.service import AgreementRecord, Servicing
from lms.settlement.errors import SettlementError
from lms_config.calendar import value_date, value_instant
from lms_config.compliance import ComplianceStore
from lms_config.exceptions import CalculationInputError
from lms_config.locked import (
    INTEREST_ON_INITIATION_NONE,
    INTEREST_ON_INITIATION_PERMITTED,
    LATE_DISBURSEMENT_ADJUST,
    LATE_DISBURSEMENT_KEEP,
    PREPAY_DROP,
    PREPAY_SHORTEN,
    REPO_FALL_CONTRACT,
    REPO_FALL_LOWER,
    TRIGGER_COLLECTIONS_DEFAULT,
    TRIGGER_CONTRACTUAL_BREACH,
    VAT_EXCLUSIVE,
    VAT_INCLUSIVE,
    OrganisationSettings,
)
from lms_config.statute import (
    DAY_COUNT_30_360,
    DAY_COUNT_ACTUAL_ACTUAL,
    SHORT_TERM_SUBSEQUENT_MONTHLY,
    SHORT_TERM_FIRST_MONTHLY,
)
from lms_config.templates import micro_short_term, unsecured_personal
from lms_config.validate import SHORT_TERM, UNSECURED
from lms.regulatory.ncr import read_ncr_number

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
_ROLE = "lms.settlement.readvance"
_FIVE = "five_percent"
_THREE = "three_percent"
_FLAGS = {
    _FIVE: SHORT_TERM_FIRST_MONTHLY,
    _THREE: SHORT_TERM_SUBSEQUENT_MONTHLY,
}
_FALLS_AWAY = "falls_away_on_default"
_DOES_NOT_FALL_AWAY = "does_not_fall_away"
_FALL_AWAY = {_FALLS_AWAY, _DOES_NOT_FALL_AWAY}
_TRIGGERS = {TRIGGER_CONTRACTUAL_BREACH, TRIGGER_COLLECTIONS_DEFAULT}
_PRODUCTS = {
    "micro_short_term": SHORT_TERM,
    "unsecured_personal": UNSECURED,
}
_OPEN = {"active", "in_arrears"}
_DAY_COUNTS = {DAY_COUNT_ACTUAL_ACTUAL, DAY_COUNT_30_360}
_VAT = {VAT_EXCLUSIVE, VAT_INCLUSIVE}
_LATE = {LATE_DISBURSEMENT_ADJUST, LATE_DISBURSEMENT_KEEP}
_PREPAY = {PREPAY_SHORTEN, PREPAY_DROP}
_INITIATION = {INTEREST_ON_INITIATION_NONE, INTEREST_ON_INITIATION_PERMITTED}
_REPO = {REPO_FALL_CONTRACT, REPO_FALL_LOWER}

# Decision 19 names. A missing value fails closed. An omitted residual is left
# null so resolve_customer_settings fills the platform default of R100.
_REQUIRED = (
    ("leniency_days", "leniency days"),
    ("full_payment_threshold_percent", "full payment threshold"),
    ("interest_on_deferred_initiation", "interest on deferred initiation fee"),
    ("repo_rate_fall", "repo-rate fall"),
    ("day_count_code", "day count"),
    ("vat_on_rand_maxima", "VAT on rand maxima"),
    ("late_disbursement", "late disbursement"),
    ("partial_prepayment", "partial prepayment"),
    ("in_duplum_trigger", "in-duplum trigger"),
    ("campaign_fall_away_choice", "campaign fall-away choice"),
)


@dataclass(frozen=True)
class ReadvanceLink:
    organisation_id: str
    readvance_id: str
    settled_agreement_id: str
    settled_loan_id: str
    settled_loan_number: str | None
    new_agreement_id: str
    new_loan_id: str
    new_loan_number: str
    new_application_number: str
    short_term_rate_flag: str | None
    supplied_rate: Decimal
    contractual_instalment_cents: int
    term_count: int
    frequency: str
    campaign_fall_away_choice: str
    campaign_fall_away_trigger: str | None
    recognition_date: date
    receipt_cents: int


@dataclass
class SettlementReadvance:
    """One process. Shares the servicing ledger and, when supplied, its loan-number series."""

    servicing: Servicing
    compliance: ComplianceStore
    loan_numbers: LoanNumberSeries
    links: dict[str, ReadvanceLink] = field(default_factory=dict)
    _idempotency: dict[tuple[str, str], tuple[str, dict]] = field(default_factory=dict, init=False, repr=False)

    def settle_and_readvance(self, body: dict | None, idempotency_key: str) -> tuple[int, dict]:
        body = body or {}
        organisation_id = body.get("organisation_id")
        if not isinstance(organisation_id, str) or not organisation_id.strip():
            return 422, {
                "outcome": "failure",
                "code": "organisation-unset",
                "message": "organisation_id is required. The audit log has no organisation to attach this failure to.",
            }
        actor_id = body.get("actor_id") if isinstance(body.get("actor_id"), str) else ""
        try:
            occurred_at, recognition = _recognition(body.get("recognised_at"))
        except SettlementError as exc:
            return self._failure(
                organisation_id=organisation_id,
                actor_id=actor_id or None,
                occurred_at=datetime.now(JOHANNESBURG),
                code=exc.code,
                message=str(exc),
                agreement_id=body.get("agreement_id") if isinstance(body.get("agreement_id"), str) else None,
                key=idempotency_key,
                fingerprint="",
                store=False,
                status=exc.status,
            )
        fingerprint = _fingerprint({"organisation_id": organisation_id, "body": body})
        if not idempotency_key:
            return self._failure(
                organisation_id=organisation_id,
                actor_id=actor_id or None,
                occurred_at=occurred_at,
                code="idempotency-required",
                message="Settlement re-advance requires an idempotency key.",
                agreement_id=body.get("agreement_id") if isinstance(body.get("agreement_id"), str) else None,
                key="",
                fingerprint=fingerprint,
                store=False,
            )
        replay = self._idempotency.get((organisation_id, idempotency_key))
        if replay is not None:
            previous, stored = replay
            if previous != fingerprint:
                return self._failure(
                    organisation_id=organisation_id,
                    actor_id=actor_id or None,
                    occurred_at=occurred_at,
                    code="idempotency-conflict",
                    message="This idempotency key was already used for a different settlement re-advance.",
                    agreement_id=body.get("agreement_id") if isinstance(body.get("agreement_id"), str) else None,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    store=False,
                    status=409,
                )
            return stored["status"], stored["body"]
        try:
            return self._perform(
                body,
                organisation_id=organisation_id,
                actor_id=actor_id,
                occurred_at=occurred_at,
                recognition=recognition,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
        except SettlementError as exc:
            extra = dict(exc.extra)
            extra.setdefault("recognition_date", recognition.isoformat())
            return self._failure(
                organisation_id=organisation_id,
                actor_id=actor_id or None,
                occurred_at=occurred_at,
                code=exc.code,
                message=str(exc),
                agreement_id=body.get("agreement_id") if isinstance(body.get("agreement_id"), str) else None,
                key=idempotency_key,
                fingerprint=fingerprint,
                store=True,
                status=exc.status,
                extra=extra,
            )

    def _perform(
        self,
        body: dict,
        *,
        organisation_id: str,
        actor_id: str,
        occurred_at: datetime,
        recognition: date,
        idempotency_key: str,
        fingerprint: str,
    ) -> tuple[int, dict]:
        if not actor_id.strip():
            raise SettlementError("actor-unset", "A staff identity is required. The audit has no actor to store.")
        agreement_id = body.get("agreement_id")
        if not isinstance(agreement_id, str) or not agreement_id.strip():
            raise SettlementError("agreement-unset", "agreement_id is required.")
        new_loan = body.get("new_loan")
        if not isinstance(new_loan, dict):
            raise SettlementError(
                "new-loan-required",
                "Settlement re-advance requires the new loan supplied by the decision engine. "
                "Early settlement without a new loan is not this command. "
                "A term or instalment change on the same agreement is a restructure and is not this command.",
            )
        agreement = self._open_agreement(organisation_id, agreement_id)
        self._actor(organisation_id, actor_id)
        try:
            self.servicing.enigma.check(organisation_id, agreement.person_id, "agreement.book")
        except ServicingError as exc:
            raise SettlementError(exc.code, str(exc), status=exc.status) from exc
        elections = _elections(body.get("settings"), body.get("product_elections"))
        self._require_ncr(organisation_id, _classification(new_loan))
        prepared = _prepare_new_loan(new_loan, elections, recognition)
        self._reject_duplicate_application(organisation_id, agreement, prepared.application_number)
        if prepared.classification == UNSECURED and not prepared.repos:
            raise SettlementError(
                "repo-unset",
                "LOCKED_DECISIONS §11: an unsecured accrual needs a repo rate. None was supplied, and none is assumed.",
            )
        _statutory_preflight(agreement, prepared, recognition)
        if type(body.get("interest_cap_present")) is not bool:
            raise SettlementError(
                "election-unset",
                "interest_cap_present must be supplied. It is not assumed.",
            )
        vat_rate = _optional_rate(body.get("vat_rate"), "vat_rate")
        receipt_cents = _cents(body.get("receipt_cents"), "receipt_cents")
        if receipt_cents <= 0:
            raise SettlementError("amount", "A settlement receipt must be a positive number of integer cents.")
        self._capitalise(
            agreement,
            recognition,
            interest_cap_present=body["interest_cap_present"],
            vat_rate=vat_rate,
        )
        try:
            required = self.servicing.ledger.settlement_balance_cents(organisation_id, agreement.ledger_loan_id or "")
        except LedgerError as exc:
            raise _from_ledger(exc) from exc
        laybye = agreement.laybye_loan_id is not None
        if receipt_cents < required or (receipt_cents > required and not laybye):
            code = "settlement-short" if receipt_cents < required else "overpayment-unset"
            message = (
                f"The settlement receipt is {receipt_cents} cents. The balance after capitalising due amounts "
                f"is {required} cents. The agreement is not settled."
                if receipt_cents < required
                else "The settlement receipt exceeds the balance and no Laybye is linked. "
                "LOCKED_DECISIONS §4 and §8 give that excess no home. The agreement is not settled."
            )
            raise SettlementError(code, message, extra={"required_cents": required})
        try:
            payment = self.servicing.accept_payment(
                organisation_id=organisation_id,
                person_id=agreement.person_id,
                cents=receipt_cents,
                recognised_at=occurred_at,
                idempotency_key=f"settlement:{idempotency_key}",
                agreement_id=agreement.agreement_id,
                attributed_due_on=recognition,
                settle=True,
            )
        except ServicingError as exc:
            raise SettlementError(exc.code, str(exc), status=exc.status) from exc
        if agreement.status != "settled":
            raise SettlementError(
                "not-settled",
                "The receipt was allocated and the balance is not 0 cents. "
                "The agreement is not marked settled and the new loan was not booked.",
                extra={"required_cents": required, "payment_id": payment.payment_id},
            )
        try:
            balance = self.servicing.ledger.settlement_balance_cents(organisation_id, agreement.ledger_loan_id or "")
        except LedgerError as exc:
            raise _from_ledger(exc) from exc
        if balance != 0:
            raise SettlementError(
                "not-settled",
                f"The balance after the settlement receipt is {balance} cents. "
                "The new loan was not booked.",
            )
        try:
            booked = self.servicing.book(
                organisation_id=organisation_id,
                person_id=agreement.person_id,
                product=prepared.product,
                settings=prepared.settings,
                recognised_at=occurred_at,
                cash_advanced_cents=prepared.cash_advanced_cents,
                frequency=prepared.frequency,
                schedule=prepared.schedule,
                initiation_fee_cents=prepared.initiation_fee_cents,
                idempotency_key=f"readvance-book:{idempotency_key}",
                repos=prepared.repos,
                rate_supplied_by_decision_engine=True,
                short_term_rate_cap=prepared.short_term_rate_cap,
            )
            booked.contractual_instalment_cents = prepared.instalment_cents
            booked.term_count = prepared.term_count
            booked.short_term_rate_flag = prepared.short_term_rate_flag
            booked.application_number = prepared.application_number
            booked.settled_from_agreement_id = agreement.agreement_id
            booked.campaign_fall_away_choice = prepared.fall_away_choice
            booked.campaign_fall_away_trigger = prepared.fall_away_trigger
            booked = self.servicing.disburse(booked.agreement_id, recognised_at=occurred_at, repos=prepared.repos)
        except ServicingError as exc:
            raise SettlementError(
                exc.code,
                "The existing agreement is settled and the new loan was not booked. " + str(exc),
                status=exc.status,
            ) from exc
        if booked.ledger_loan_id is None:
            raise SettlementError(
                "not-disbursed",
                "The existing agreement is settled and the new loan was not disbursed.",
            )
        try:
            number = self.loan_numbers.issue(
                organisation_id=organisation_id,
                application_number=prepared.application_number,
                agreement_id=booked.agreement_id,
                ledger_loan_id=booked.ledger_loan_id,
            )
        except PaymentRailError as exc:
            raise SettlementError(
                exc.code,
                "The existing agreement is settled and the new loan has no loan number. " + str(exc),
            ) from exc
        settled_number = self.loan_numbers.find_by_agreement(organisation_id, agreement.agreement_id)
        link = ReadvanceLink(
            organisation_id=organisation_id,
            readvance_id=str(uuid4()),
            settled_agreement_id=agreement.agreement_id,
            settled_loan_id=agreement.ledger_loan_id or "",
            settled_loan_number=None if settled_number is None else settled_number.loan_number,
            new_agreement_id=booked.agreement_id,
            new_loan_id=booked.ledger_loan_id,
            new_loan_number=number.loan_number,
            new_application_number=prepared.application_number,
            short_term_rate_flag=prepared.short_term_rate_flag,
            supplied_rate=prepared.rate,
            contractual_instalment_cents=prepared.instalment_cents,
            term_count=prepared.term_count,
            frequency=prepared.frequency,
            campaign_fall_away_choice=prepared.fall_away_choice,
            campaign_fall_away_trigger=prepared.fall_away_trigger,
            recognition_date=recognition,
            receipt_cents=receipt_cents,
        )
        self.links[link.readvance_id] = link
        settled_label = link.settled_loan_number or agreement.agreement_id
        confirmation = (
            f"Loan {link.new_loan_number} is booked and linked to settled loan {settled_label}. "
            "The balance is 0 cents."
        )
        result = {
            "outcome": "success",
            "confirmation": confirmation,
            "recognition_date": recognition.isoformat(),
            "settled_agreement_id": link.settled_agreement_id,
            "settled_loan_id": link.settled_loan_id,
            "settled_loan_number": link.settled_loan_number,
            "new_agreement_id": link.new_agreement_id,
            "new_loan_id": link.new_loan_id,
            "new_loan_number": link.new_loan_number,
            "new_application_number": link.new_application_number,
            "short_term_rate_flag": link.short_term_rate_flag,
            "supplied_rate": str(link.supplied_rate),
            "contractual_instalment_cents": link.contractual_instalment_cents,
            "term_count": link.term_count,
            "receipt_cents": receipt_cents,
            "balance_cents": 0,
        }
        self._audit(
            organisation_id=organisation_id,
            actor_id=actor_id,
            occurred_at=occurred_at,
            agreement_id=agreement.agreement_id,
            payload={"outcome": "success", "confirmation": confirmation, **_audit_link(link)},
        )
        self._idempotency[(organisation_id, idempotency_key)] = (
            fingerprint,
            {"status": 200, "body": result},
        )
        return 200, result

    def _capitalise(
        self,
        agreement: AgreementRecord,
        recognition: date,
        *,
        interest_cap_present: bool,
        vat_rate: Decimal | None,
    ) -> None:
        account = self.servicing.ledger.store.get(agreement.organisation_id, agreement.ledger_loan_id or "")
        if account.disbursement_value_date is None:
            raise SettlementError("not-disbursed", "The agreement has not been disbursed.")
        if recognition < account.disbursement_value_date:
            raise SettlementError(
                "value-date",
                "The recognition date is before the disbursement value date.",
            )
        end = min(recognition, account.contractual_end)
        day = account.disbursement_value_date
        while day <= end:
            try:
                self.servicing.ledger.accrue_day(
                    organisation_id=agreement.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(day),
                    interest_cap_present=interest_cap_present,
                )
            except LedgerError as exc:
                if exc.code not in {"already-accrued", "outside-term"}:
                    raise _from_ledger(exc) from exc
            except CalculationInputError as exc:
                raise SettlementError("election-unset", str(exc)) from exc
            day += timedelta(days=1)
        try:
            self.servicing.ledger.bill_interest(
                organisation_id=agreement.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(recognition),
            )
        except LedgerError as exc:
            raise _from_ledger(exc) from exc
        self._levy_service_fees(agreement, recognition, vat_rate=vat_rate, interest_cap_present=interest_cap_present)

    def _levy_service_fees(
        self,
        agreement: AgreementRecord,
        recognition: date,
        *,
        vat_rate: Decimal | None,
        interest_cap_present: bool,
    ) -> None:
        monthly = _service_fee_cents(agreement)
        account = self.servicing.ledger.store.get(agreement.organisation_id, agreement.ledger_loan_id or "")
        if monthly == 0 or account.disbursement_value_date is None:
            return
        first_due = min(due for due, _amount in agreement.schedule)
        disbursement = account.disbursement_value_date
        pending = [
            month
            for month in _months(disbursement, recognition)
            if month not in account.service_months
        ]
        if pending and vat_rate is None:
            raise SettlementError(
                "vat-rate-unset",
                "LOCKED_DECISIONS §9: the LMS calculates VAT. No rate was supplied, and none is assumed.",
            )
        for year, month in pending:
            opening = (year, month) == (disbursement.year, disbursement.month)
            if opening:
                levy_day = disbursement
                due_on = first_due if first_due <= recognition else recognition
                self._levy_once(
                    agreement,
                    recognised_at=value_instant(levy_day),
                    monthly_cents=monthly,
                    due_on=due_on,
                    interest_cap_present=interest_cap_present,
                    vat_rate=vat_rate,
                    opening=True,
                    first_due=first_due,
                )
                continue
            if (year, month) == (recognition.year, recognition.month):
                levy_day = recognition
            else:
                levy_day = date(year, month, 1)
            self._levy_once(
                agreement,
                recognised_at=value_instant(levy_day),
                monthly_cents=monthly,
                due_on=levy_day,
                interest_cap_present=interest_cap_present,
                vat_rate=vat_rate,
                opening=False,
                first_due=None,
            )

    def _levy_once(self, agreement: AgreementRecord, **kwargs) -> None:
        try:
            self.servicing.ledger.levy_service_fee(
                organisation_id=agreement.organisation_id,
                loan_id=agreement.ledger_loan_id or "",
                **kwargs,
            )
        except LedgerError as exc:
            if exc.code != "service-fee-once":
                raise _from_ledger(exc) from exc
        except CalculationInputError as exc:
            raise SettlementError("election-unset", str(exc)) from exc

    def _open_agreement(self, organisation_id: str, agreement_id: str) -> AgreementRecord:
        agreement = self.servicing.agreements.get(agreement_id)
        if agreement is None or agreement.organisation_id != organisation_id:
            raise SettlementError("not-found", "No agreement with that id for this organisation.", status=404)
        if agreement.status not in _OPEN or agreement.ledger_loan_id is None:
            raise SettlementError(
                "status",
                f"Cannot settle an agreement in {agreement.status}. "
                "Restructure of the same agreement is not this command.",
            )
        return agreement

    def _actor(self, organisation_id: str, actor_id: str) -> None:
        try:
            self.servicing.enigma.check(organisation_id, actor_id, _ROLE)
        except ServicingError as exc:
            raise SettlementError(exc.code, str(exc), status=exc.status) from exc

    def _require_ncr(self, organisation_id: str, classification: str) -> None:
        if classification not in {SHORT_TERM, UNSECURED}:
            raise SettlementError(
                "classification-unsupported",
                "Settlement re-advance books a short-term or unsecured agreement. "
                "No other classification is assumed.",
            )
        number = read_ncr_number(self.compliance, organisation_id)
        if number is None:
            raise SettlementError(
                "ncr-number-unset",
                "missing NCR registration number. Decision 21: the number is compulsory for a "
                "short-term or unsecured agreement. Enigma does not supply it.",
            )

    def _reject_duplicate_application(
        self,
        organisation_id: str,
        agreement: AgreementRecord,
        application_number: str,
    ) -> None:
        existing = self.loan_numbers.find_application(organisation_id, application_number)
        if existing is not None:
            raise SettlementError(
                "loan-number",
                "LOCKED_DECISIONS §25: there is only one loan number for an application. "
                "The decision engine must supply the new loan's own application number.",
            )
        settled = self.loan_numbers.find_by_agreement(organisation_id, agreement.agreement_id)
        if settled is not None and settled.application_number == application_number:
            raise SettlementError(
                "loan-number",
                "LOCKED_DECISIONS §25: there is only one loan number for an application.",
            )

    def _failure(
        self,
        *,
        organisation_id: str,
        actor_id: str | None,
        occurred_at: datetime,
        code: str,
        message: str,
        agreement_id: str | None,
        key: str,
        fingerprint: str,
        store: bool,
        status: int = 422,
        extra: dict | None = None,
    ) -> tuple[int, dict]:
        result = {"outcome": "failure", "code": code, "message": message}
        if extra:
            result.update(extra)
        self._audit(
            organisation_id=organisation_id,
            actor_id=actor_id,
            occurred_at=occurred_at,
            agreement_id=agreement_id,
            payload={"outcome": "failure", "code": code, "message": message, **(extra or {})},
        )
        if store and key:
            self._idempotency[(organisation_id, key)] = (fingerprint, {"status": status, "body": result})
        return status, result

    def _audit(
        self,
        *,
        organisation_id: str,
        actor_id: str | None,
        occurred_at: datetime,
        agreement_id: str | None,
        payload: dict,
    ) -> None:
        self.servicing.audit.append(
            organisation_id=organisation_id,
            occurred_at=occurred_at,
            event_type="SETTLEMENT_READVANCE",
            category="operational",
            agreement_id=agreement_id,
            enigma_person_id=actor_id,
            payload=payload,
        )


@dataclass(frozen=True)
class _Prepared:
    classification: str
    product: object
    settings: OrganisationSettings
    rate: Decimal
    short_term_rate_flag: str | None
    short_term_rate_cap: Decimal | None
    term_count: int
    frequency: str
    instalment_cents: int
    cash_advanced_cents: int
    initiation_fee_cents: int
    schedule: tuple[tuple[date, int], ...]
    application_number: str
    repos: tuple[RepoRate, ...]
    fall_away_choice: str
    fall_away_trigger: str | None


def _prepare_new_loan(raw: dict, elections: dict, recognition: date) -> _Prepared:
    classification = _classification(raw)
    rate = _rate(raw.get("rate"))
    flag = raw.get("short_term_rate_flag")
    cap: Decimal | None
    if classification == SHORT_TERM:
        if flag not in _FLAGS:
            raise SettlementError(
                "short-term-flag-unset",
                "The decision engine must supply the 5% / 3% short-term flag as "
                "five_percent or three_percent. The LMS does not choose one.",
            )
        cap = _FLAGS[flag]
        if rate > cap:
            raise SettlementError(
                "short-term-rate",
                "The rate supplied by the decision engine exceeds the cap for the supplied "
                "5% / 3% flag. The LMS does not choose a different flag.",
            )
    else:
        if flag is not None:
            raise SettlementError(
                "short-term-flag-unset",
                "The 5% / 3% flag is the short-term distinction. It is not stored on an unsecured loan.",
            )
        cap = None
        flag = None
    term_count = _cents(raw.get("term_count"), "term_count")
    if term_count <= 0:
        raise SettlementError("term", "The decision engine term count must be a positive integer.")
    frequency = raw.get("frequency")
    if frequency not in FREQUENCIES:
        raise SettlementError(
            "frequency-unsupported",
            "The decision engine frequency is not one of weekly, fortnightly, monthly, quarterly, bi_annual, or annual.",
        )
    instalment_cents = _cents(raw.get("instalment_cents"), "instalment_cents")
    if instalment_cents < 0:
        raise SettlementError("amount", "The contractual instalment cannot be negative.")
    cash = _cents(raw.get("cash_advanced_cents"), "cash_advanced_cents")
    if cash <= 0:
        raise SettlementError("principal", "Cash advanced must be a positive number of integer cents.")
    initiation = raw.get("initiation_fee_cents", 0)
    initiation_fee = _cents(initiation, "initiation_fee_cents")
    if initiation_fee < 0:
        raise SettlementError("initiation", "Initiation fee cannot be negative.")
    schedule = _schedule(raw.get("schedule"), recognition)
    if len(schedule) != term_count:
        raise SettlementError(
            "term",
            "The decision engine term count does not match the number of schedule lines. "
            "The LMS does not build a schedule.",
        )
    application = raw.get("application_number")
    if not isinstance(application, str) or not application.strip():
        raise SettlementError(
            "application-number-unset",
            "LOCKED_DECISIONS §25: the decision engine supplies an application number. "
            "A blank application number is not given a loan number.",
        )
    day_count = elections["day_count_code"]
    if classification == SHORT_TERM:
        template = micro_short_term()
        credit = replace(
            template.instruments[0],
            monthly_rate=rate,
            base_rate=rate,
            discount_rate=Decimal(0),
            day_count=day_count,
        )
    else:
        template = unsecured_personal()
        credit = replace(
            template.instruments[0],
            repo_margin=rate,
            base_rate=rate,
            discount_rate=Decimal(0),
            annual_rate=None,
            day_count=day_count,
        )
    product = replace(template, instruments=(credit,))
    settings = OrganisationSettings(
        leniency_days=elections["leniency_days"],
        full_payment_threshold_percent=elections["full_payment_threshold_percent"],
        interest_on_deferred_initiation=elections["interest_on_deferred_initiation"],
        repo_rate_fall=elections["repo_rate_fall"],
        day_count_code=day_count,
        base_rate=rate,
        discount_rate=Decimal(0),
        vat_on_rand_maxima=elections["vat_on_rand_maxima"],
        late_disbursement=elections["late_disbursement"],
        partial_prepayment=elections["partial_prepayment"],
        in_duplum_trigger=elections["in_duplum_trigger"],
        residual_write_off_threshold_cents=elections["residual_write_off_threshold_cents"],
    )
    return _Prepared(
        classification=classification,
        product=product,
        settings=settings,
        rate=rate,
        short_term_rate_flag=flag,
        short_term_rate_cap=cap,
        term_count=term_count,
        frequency=frequency,
        instalment_cents=instalment_cents,
        cash_advanced_cents=cash,
        initiation_fee_cents=initiation_fee,
        schedule=schedule,
        application_number=application.strip(),
        repos=_repos(raw.get("repos")),
        fall_away_choice=elections["campaign_fall_away_choice"],
        fall_away_trigger=elections["campaign_fall_away_trigger"],
    )


def _statutory_preflight(agreement: AgreementRecord, prepared: _Prepared, recognition: date) -> None:
    """Check the Act limits for the supplied rate. Do not count other loans."""
    if prepared.classification == SHORT_TERM:
        product = Product.MICRO
        agreed = prepared.rate
        margin = Decimal("0.21")
    else:
        product = Product.PERSONAL
        agreed = None
        margin = prepared.rate
    try:
        Agreement(
            product=product,
            credit_provider_org_id=agreement.organisation_id,
            consumer_party_id=agreement.person_id,
            product_enrolment_id=agreement.enrolment_id,
            cash_advanced_cents=prepared.cash_advanced_cents,
            advance_date=recognition,
            maturity_date=max(due for due, _amount in prepared.schedule),
            agreed_monthly_rate=agreed,
            margin_annual=margin,
            prior_short_term_inceptions=(),
            principal_instalments=prepared.schedule,
            campaign_interest_discount=Decimal(0),
        )
    except (RuleError, CalculationInputError) as exc:
        raise SettlementError(getattr(exc, "code", "engine-rejected"), str(exc)) from exc


def _elections(settings, product_elections) -> dict:
    if not isinstance(settings, dict):
        raise SettlementError("election-unset", "missing election: settings")
    if product_elections is None:
        product_elections = {}
    if not isinstance(product_elections, dict):
        raise SettlementError("election-unset", "product_elections must be an object when it is sent.")
    merged: dict = {}
    for key, label in _REQUIRED:
        if key == "campaign_fall_away_choice":
            continue
        if key in product_elections and product_elections[key] is not None:
            merged[key] = product_elections[key]
        else:
            merged[key] = settings.get(key)
        if merged[key] is None:
            raise SettlementError("election-unset", f"missing election: {label}")
    if product_elections.get("campaign_fall_away_choice") is not None:
        choice = product_elections.get("campaign_fall_away_choice")
        trigger = product_elections.get("campaign_fall_away_trigger")
    else:
        choice = settings.get("campaign_fall_away_choice")
        trigger = settings.get("campaign_fall_away_trigger")
    merged["campaign_fall_away_choice"] = choice
    if type(merged["leniency_days"]) is not int or merged["leniency_days"] < 0:
        raise SettlementError("election-unset", "missing election: leniency days")
    merged["full_payment_threshold_percent"] = _threshold(merged["full_payment_threshold_percent"])
    _one(merged["interest_on_deferred_initiation"], _INITIATION, "interest on deferred initiation fee")
    _one(merged["repo_rate_fall"], _REPO, "repo-rate fall")
    _one(merged["day_count_code"], _DAY_COUNTS, "day count")
    _one(merged["vat_on_rand_maxima"], _VAT, "VAT on rand maxima")
    _one(merged["late_disbursement"], _LATE, "late disbursement")
    _one(merged["partial_prepayment"], _PREPAY, "partial prepayment")
    _one(merged["in_duplum_trigger"], _TRIGGERS, "in-duplum trigger")
    if (
        "residual_write_off_threshold_cents" in product_elections
        and product_elections["residual_write_off_threshold_cents"] is not None
    ):
        residual = product_elections["residual_write_off_threshold_cents"]
    else:
        residual = settings.get("residual_write_off_threshold_cents")
    if residual is not None and (type(residual) is not int or residual < 0):
        raise SettlementError(
            "election-unset",
            "missing election: residual write-off threshold",
        )
    merged["residual_write_off_threshold_cents"] = residual
    choice = merged["campaign_fall_away_choice"]
    _check_fall_away(choice)
    if choice == _DOES_NOT_FALL_AWAY:
        if trigger is not None:
            raise SettlementError(
                "election-unset",
                "missing election: campaign fall-away trigger. A campaign that does not fall away has no trigger.",
            )
        trigger = None
    elif trigger not in _TRIGGERS:
        raise SettlementError(
            "election-unset",
            "missing election: campaign fall-away trigger",
        )
    merged["campaign_fall_away_choice"] = choice
    merged["campaign_fall_away_trigger"] = trigger
    return merged


def _check_fall_away(choice) -> None:
    if choice not in _FALL_AWAY:
        raise SettlementError(
            "election-unset",
            "missing election: campaign fall-away choice",
        )


def _classification(raw: dict) -> str:
    code = raw.get("product_code")
    if code not in _PRODUCTS:
        raise SettlementError(
            "election-unset",
            "product_code must name a Day-1 template. No product is assumed.",
        )
    return _PRODUCTS[code]


def _one(value, allowed: set[str], label: str) -> None:
    if value not in allowed:
        raise SettlementError("election-unset", f"missing election: {label}")


def _threshold(value) -> Decimal:
    if isinstance(value, float) or value is None:
        raise SettlementError("election-unset", "missing election: full payment threshold")
    try:
        if isinstance(value, str):
            number = Decimal(value)
        elif type(value) is int or isinstance(value, Decimal):
            number = Decimal(value)
        else:
            raise InvalidOperation
    except InvalidOperation as exc:
        raise SettlementError("election-unset", "missing election: full payment threshold") from exc
    if number <= 0 or number > 100:
        raise SettlementError(
            "election-unset",
            "missing election: full payment threshold",
        )
    return number


def _rate(value) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise SettlementError(
            "rate",
            "The decision-engine rate must be a decimal string in the unit the ledger already stores. "
            "No conversion is applied.",
        )
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise SettlementError(
            "rate",
            "The decision-engine rate must be a decimal string. No conversion is applied.",
        ) from exc
    if rate < 0:
        raise SettlementError("rate", "The decision-engine rate cannot be negative.")
    return rate


def _optional_rate(value, label: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SettlementError(label, f"{label} must be a decimal string. No rate is assumed.")
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise SettlementError(label, f"{label} must be a decimal string. No rate is assumed.") from exc
    if rate < 0:
        raise SettlementError(label, f"{label} cannot be negative.")
    return rate


def _cents(value, label: str) -> int:
    if type(value) is not int:
        raise SettlementError("amount", f"{label} must be an integer number of cents.")
    return value


def _schedule(raw, recognition: date) -> tuple[tuple[date, int], ...]:
    if not isinstance(raw, list) or not raw:
        raise SettlementError("schedule", "A schedule is required. Servicing does not build one.")
    lines: list[tuple[date, int]] = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise SettlementError("schedule", "Each schedule line is a due date and an integer number of cents.")
        due_raw, amount = row
        if not isinstance(due_raw, str):
            raise SettlementError("schedule", "Each schedule due date is a calendar date.")
        try:
            due = date.fromisoformat(due_raw)
        except ValueError as exc:
            raise SettlementError("schedule", "Each schedule due date is a calendar date.") from exc
        cents = _cents(amount, "schedule amount")
        if cents <= 0:
            raise SettlementError("schedule", "Each principal line must be a positive number of cents.")
        if due < recognition:
            raise SettlementError("schedule", "A principal due date is before the recognition date.")
        lines.append((due, cents))
    return tuple(lines)


def _repos(raw) -> tuple[RepoRate, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SettlementError("repo-unset", "repos must be a list when it is sent. No repo rate is assumed.")
    found: list[RepoRate] = []
    for row in raw:
        if not isinstance(row, dict):
            raise SettlementError("repo-unset", "Each repo row needs an effective date and a decimal annual rate.")
        effective = row.get("effective_from")
        if not isinstance(effective, str):
            raise SettlementError("repo-unset", "Each repo row needs an effective date and a decimal annual rate.")
        try:
            found.append(RepoRate(date.fromisoformat(effective), _rate(row.get("annual_rate"))))
        except (ValueError, SettlementError) as exc:
            if isinstance(exc, SettlementError):
                raise SettlementError("repo-unset", str(exc)) from exc
            raise SettlementError("repo-unset", "Each repo effective date is a calendar date.") from exc
    return tuple(found)


def _recognition(raw) -> tuple[datetime, date]:
    if not isinstance(raw, str) or not raw.strip():
        raise SettlementError(
            "value-date",
            "LOCKED_DECISIONS §1: recognised_at is required and must carry a timezone.",
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SettlementError(
            "value-date",
            "LOCKED_DECISIONS §1: recognised_at must be a timezone-aware timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise SettlementError(
            "value-date",
            "LOCKED_DECISIONS §1: recognised_at must carry a timezone. The recognition date is 00:00 Africa/Johannesburg.",
        )
    recognition = value_date(parsed)
    return value_instant(recognition), recognition


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def _service_fee_cents(agreement: AgreementRecord) -> int:
    for instrument in agreement.product.instruments:
        for fee in instrument.fees:
            if fee.code == "service":
                return fee.amount_cents
    return 0


def _from_ledger(exc: LedgerError) -> SettlementError:
    return SettlementError(exc.code, str(exc))


def _audit_link(link: ReadvanceLink) -> dict:
    return {
        "readvance_id": link.readvance_id,
        "settled_agreement_id": link.settled_agreement_id,
        "settled_loan_id": link.settled_loan_id,
        "settled_loan_number": link.settled_loan_number,
        "new_agreement_id": link.new_agreement_id,
        "new_loan_id": link.new_loan_id,
        "new_loan_number": link.new_loan_number,
        "new_application_number": link.new_application_number,
        "short_term_rate_flag": link.short_term_rate_flag,
        "supplied_rate": str(link.supplied_rate),
        "contractual_instalment_cents": link.contractual_instalment_cents,
        "term_count": link.term_count,
        "receipt_cents": link.receipt_cents,
        "recognition_date": link.recognition_date.isoformat(),
    }


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
