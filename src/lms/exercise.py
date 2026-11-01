"""Exercise a booking and a payment through the existing stubs.

The quote stub supplies the application number, the rate already on the
Day-1 template, and the credit-life premium. The debit-file stub turns one
instruction into a receipt. ``Servicing.book`` and ``Servicing.accept_payment``
remain the only writers. A blank election is not filled in here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from lms.objects import ObjectStoreError
from lms.payments.loan_numbers import LoanNumberSeries
from lms.payments.models import CollectionInstructionRecord, DebitOrderFile
from lms.servicing.service import Servicing
from lms.stubs.debit_file import DebitFileStub
from lms.stubs.decision_quote import DecisionQuoteStub, QuoteRequest
from lms.stubs.wire import apply_debit_receipts, book_quoted
from lms_config.exceptions import CalculationInputError
from lms_config.locked import OrganisationSettings, resolve_customer_settings
from lms_config.templates import micro_short_term, unsecured_personal

_PRODUCTS = {
    "micro_short_term": micro_short_term,
    "unsecured_personal": unsecured_personal,
}

_ELECTIONS = (
    "leniency_days",
    "full_payment_threshold_percent",
    "interest_on_deferred_initiation",
    "repo_rate_fall",
    "day_count_code",
    "vat_on_rand_maxima",
    "late_disbursement",
    "partial_prepayment",
    "in_duplum_trigger",
)

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_BRAND_LIMIT = 1_000_000


class ExerciseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Exercise:
    """One process. Agreements live in memory, as the servicing layer does."""

    def __init__(self, objects=None) -> None:
        self.servicing = Servicing()
        self.quotes = DecisionQuoteStub()
        self.loan_numbers = LoanNumberSeries()
        self.objects = objects

    def book(self, form: dict) -> dict:
        organisation_id = _required(form, "organisation_id")
        person_id = _required(form, "person_id")
        full_name = _required(form, "full_name", code="identity-unset")
        id_number = _required(form, "id_number", code="identity-unset")
        service_address = _required(form, "service_address", code="identity-unset")
        idempotency_key = _required(form, "idempotency_key")
        frequency = _required(form, "frequency")
        product = _product(form)
        settings = _settings(form)
        try:
            resolve_customer_settings(settings, product)
        except CalculationInputError as exc:
            raise ExerciseError("election-unset", str(exc)) from exc
        cash = _cents(form, "cash_advanced_cents")
        due_on = _date(form, "due_on")
        schedule_amount = _cents(form, "schedule_amount_cents")
        recognised_at = _instant(form, "recognised_at")
        disbursed_at = _instant(form, "disbursed_at")
        self.servicing.enigma.full_name = full_name
        self.servicing.enigma.id_number = id_number
        self.servicing.enigma.service_address = service_address
        self.servicing.enigma.mode = "active"
        approval = self.quotes.quote(
            QuoteRequest(
                organisation_id=organisation_id,
                person_id=person_id,
                product=product,
                settings=settings,
                recognised_at=recognised_at,
                cash_advanced_cents=cash,
                frequency=frequency,
                schedule=((due_on, schedule_amount),),
                idempotency_key=idempotency_key,
                initiation_fee_cents=0,
            )
        )
        record = book_quoted(self.servicing, approval)
        record = self.servicing.disburse(record.agreement_id, recognised_at=disbursed_at)
        if not record.ledger_loan_id or not record.application_number:
            raise ExerciseError(
                "loan-number",
                "The disbursed agreement has no ledger loan or application number, so no loan number is issued.",
            )
        number = self.loan_numbers.issue(
            organisation_id=record.organisation_id,
            application_number=record.application_number,
            agreement_id=record.agreement_id,
            ledger_loan_id=record.ledger_loan_id,
        )
        return {
            "agreement_id": record.agreement_id,
            "status": record.status,
            "loan_number": number.loan_number,
            "application_number": record.application_number,
            "credit_life_premium_cents": record.credit_life_premium_cents,
            "frozen_full_name": record.frozen_full_name,
            "frozen_id_number": record.frozen_id_number,
            "organisation_id": record.organisation_id,
            "person_id": record.person_id,
        }

    def pay(self, form: dict) -> dict:
        agreement_id = _required(form, "agreement_id")
        record = self.servicing.agreements.get(agreement_id)
        if record is None:
            raise ExerciseError(
                "agreement-missing",
                "That agreement is not in this process. Book it before taking a receipt.",
            )
        number = self.loan_numbers.find_by_agreement(record.organisation_id, record.agreement_id)
        if number is None:
            raise ExerciseError(
                "loan-number-unset",
                "LOCKED_DECISIONS §25: the LMS loan number is not on this agreement.",
            )
        amount = _cents(form, "amount_cents")
        due_on = _date(form, "due_on")
        recognition = _date(form, "recognition_date")
        outcome = form.get("outcome", "").strip()
        if outcome not in {"success", "failure"}:
            raise ExerciseError(
                "outcome-unset",
                "Say whether the debit-order stub returns success or failure. It is not assumed.",
            )
        failed = frozenset({number.loan_number}) if outcome == "failure" else frozenset()
        file = DebitOrderFile(
            organisation_id=record.organisation_id,
            recognition_date=recognition,
            due_on=due_on,
            instructions=(
                CollectionInstructionRecord(
                    loan_number=number.loan_number,
                    amount_cents=amount,
                    due_on=due_on,
                    recognition_date=recognition,
                    credit_life_premium_cents=record.credit_life_premium_cents,
                    purpose="loan_instalment",
                    scheme="eft",
                    agreement_id=record.agreement_id,
                    application_number=record.application_number or "",
                ),
            ),
            body="",
        )
        receipts = DebitFileStub(failed).acknowledge(file)
        applied = apply_debit_receipts(self.servicing, receipts)
        receipt = receipts[0]
        result = applied[0]
        paid = getattr(result, "payment_id", None)
        return {
            "kind": receipt.kind,
            "loan_number": number.loan_number,
            "reason_code": getattr(receipt, "reason_code", ""),
            "payment_id": paid or "",
            "payment_status": getattr(result, "status", ""),
            "amount_cents": getattr(result, "cents", ""),
            "agreement_id": agreement_id,
        }

    def issue_statement(self, form: dict) -> dict:
        organisation_id = _required(form, "organisation_id")
        person_id = _required(form, "person_id")
        period_start = _date(form, "period_start")
        period_end = _date(form, "period_end")
        cap = form.get("interest_cap_present", "").strip()
        if cap not in {"true", "false"}:
            raise ExerciseError(
                "election-unset",
                "interest_cap_present must be supplied. Servicing does not assume a cap row exists.",
            )
        vat_raw = form.get("vat_rate", "").strip()
        vat = None if vat_raw == "" else Decimal(vat_raw)
        issued = self.servicing.issue_statement(
            organisation_id=organisation_id,
            person_id=person_id,
            period_start=period_start,
            period_end=period_end,
            vat_rate=vat,
            interest_cap_present=cap == "true",
        )
        key = f"statements/{_segment(organisation_id)}/{issued.statement_id}.json"
        stored = self._put(key, issued.pdf_stub, "application/json")
        return {
            "statement_id": issued.statement_id,
            "pdf_sha256": issued.pdf_sha256,
            "object_key": stored,
            "organisation_id": organisation_id,
            "person_id": person_id,
        }

    def store_brand(self, form: dict) -> dict:
        organisation_id = _segment(_required(form, "organisation_id"))
        asset_name = _segment(_required(form, "asset_name"), code="brand-unset")
        body = form.get("body", "")
        if body == "":
            raise ExerciseError("brand-unset", "The brand asset body is empty.")
        raw = body.encode("utf-8")
        if len(raw) > _BRAND_LIMIT:
            raise ExerciseError("brand-unset", "The brand asset is larger than this test store accepts.")
        key = f"brand/{organisation_id}/{asset_name}"
        stored = self._put(key, raw, "text/plain; charset=utf-8")
        return {"object_key": stored, "organisation_id": organisation_id, "asset_name": asset_name}

    def agreements(self) -> list[dict]:
        rows = []
        for record in self.servicing.agreements.values():
            number = self.loan_numbers.find_by_agreement(record.organisation_id, record.agreement_id)
            rows.append(
                {
                    "agreement_id": record.agreement_id,
                    "loan_number": "" if number is None else number.loan_number,
                    "application_number": record.application_number or "",
                    "status": record.status,
                    "person_id": record.person_id,
                    "organisation_id": record.organisation_id,
                    "cash_advanced_cents": record.cash_advanced_cents,
                }
            )
        rows.sort(key=lambda row: row["loan_number"])
        return rows

    def _put(self, key: str, body: bytes, content_type: str) -> str:
        if self.objects is None:
            raise ExerciseError(
                "object-store-unset",
                "No statement bucket is configured. The artifact was not stored.",
            )
        try:
            return self.objects.put(key, body, content_type)
        except ObjectStoreError as exc:
            raise ExerciseError(exc.code, str(exc)) from exc


def _product(form: dict):
    code = form.get("product_code", "").strip()
    if code not in _PRODUCTS:
        raise ExerciseError("election-unset", "product_code must name a Day-1 template. No product is assumed.")
    return _PRODUCTS[code]()


def _settings(form: dict) -> OrganisationSettings:
    missing = [name for name in _ELECTIONS if not str(form.get(name, "")).strip()]
    if missing:
        raise ExerciseError("election-unset", f"missing election: {missing[0]}")
    try:
        threshold = Decimal(str(form["full_payment_threshold_percent"]).strip())
        leniency = int(str(form["leniency_days"]).strip())
    except (ArithmeticError, ValueError) as exc:
        raise ExerciseError("election-unset", "An election value is not usable.") from exc
    residual = str(form.get("residual_write_off_threshold_cents", "")).strip()
    residual_cents = None
    if residual:
        try:
            residual_cents = int(residual)
        except ValueError as exc:
            raise ExerciseError("election-unset", "missing election: residual write-off threshold") from exc
    return OrganisationSettings(
        leniency_days=leniency,
        full_payment_threshold_percent=threshold,
        interest_on_deferred_initiation=form["interest_on_deferred_initiation"].strip(),
        repo_rate_fall=form["repo_rate_fall"].strip(),
        day_count_code=form["day_count_code"].strip(),
        vat_on_rand_maxima=form["vat_on_rand_maxima"].strip(),
        late_disbursement=form["late_disbursement"].strip(),
        partial_prepayment=form["partial_prepayment"].strip(),
        in_duplum_trigger=form["in_duplum_trigger"].strip(),
        residual_write_off_threshold_cents=residual_cents,
    )


def _required(form: dict, name: str, *, code: str = "missing") -> str:
    value = str(form.get(name, "")).strip()
    if not value:
        raise ExerciseError(code, f"{name} is required.")
    return value


def _cents(form: dict, name: str) -> int:
    raw = _required(form, name)
    if not raw.isdigit():
        raise ExerciseError("amount", f"{name} must be zero or a positive number of integer cents.")
    return int(raw)


def _date(form: dict, name: str) -> date:
    raw = _required(form, name)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ExerciseError("value-date", f"{name} must be a calendar date.") from exc


def _instant(form: dict, name: str) -> datetime:
    raw = _required(form, name)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ExerciseError("value-date", f"{name} must be an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise ExerciseError("value-date", "A recognition timestamp must carry a timezone.")
    return parsed


def _segment(value: str, *, code: str = "missing") -> str:
    if not _SEGMENT.fullmatch(value):
        raise ExerciseError(code, "Use letters, digits, and . _ - for this identifier.")
    return value
