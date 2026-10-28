"""HTTP-shaped contracts for the servicing workflows. No session middleware."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing
from lms_config.exceptions import CalculationInputError
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term, unsecured_personal

_PRODUCTS = {
    "micro_short_term": micro_short_term,
    "unsecured_personal": unsecured_personal,
}


def dispatch(servicing: Servicing, method: str, path: str, body: dict | None, headers: dict | None) -> tuple[int, dict]:
    body = body or {}
    headers = headers or {}
    try:
        return 200, _route(servicing, method.upper(), path, body, headers)
    except ServicingError as exc:
        return exc.status, {"code": exc.code, "message": str(exc)}
    except CalculationInputError as exc:
        return 422, {"code": "election-unset", "message": str(exc)}


def _route(servicing: Servicing, method: str, path: str, body: dict, headers: dict) -> dict:
    parts = [part for part in path.split("/") if part]
    if method == "POST" and parts == ["v1", "agreements"]:
        record = servicing.book(
            organisation_id=_required(body, "organisation_id"),
            person_id=_required(body, "person_id"),
            product=_product(body),
            settings=_settings(body.get("settings") or {}),
            recognised_at=_instant(body, "recognised_at"),
            cash_advanced_cents=int(_required(body, "cash_advanced_cents")),
            frequency=_required(body, "frequency"),
            schedule=_schedule(body),
            initiation_fee_cents=int(body.get("initiation_fee_cents") or 0),
            quoted_disbursement=_optional_date(body.get("quoted_disbursement")),
            idempotency_key=headers.get("Idempotency-Key", ""),
        )
        return _agreement(record)
    if method == "POST" and len(parts) == 4 and parts[:2] == ["v1", "agreements"] and parts[3] == "disbursements":
        record = servicing.disburse(parts[2], recognised_at=_instant(body, "recognised_at"))
        return _agreement(record)
    if method == "POST" and parts == ["v1", "payments"]:
        payment = servicing.accept_payment(
            organisation_id=_required(body, "organisation_id"),
            person_id=_required(body, "person_id"),
            cents=int(_required(body, "cents")),
            recognised_at=_instant(body, "recognised_at"),
            idempotency_key=headers.get("Idempotency-Key", ""),
            agreement_id=body.get("agreement_id"),
            attributed_due_on=_optional_date(body.get("attributed_due_on")),
        )
        return _payment(payment)
    if method == "POST" and len(parts) == 4 and parts[:2] == ["v1", "payments"] and parts[3] == "reversals":
        payment = servicing.reverse_payment(parts[2], recognised_at=_instant(body, "recognised_at"))
        return _payment(payment)
    if method == "POST" and len(parts) == 5 and parts[:2] == ["v1", "payments"] and parts[3] == "applications":
        payment = servicing.apply_payment(
            parts[2],
            agreement_id=_required(body, "agreement_id"),
            attributed_due_on=_date(_required(body, "attributed_due_on")),
        )
        return _payment(payment)
    if (
        method == "POST"
        and len(parts) == 6
        and parts[0] == "v1"
        and parts[1] == "organisations"
        and parts[3] == "clients"
        and parts[5] == "statements"
    ):
        issued = servicing.issue_statement(
            organisation_id=parts[2],
            person_id=parts[4],
            period_start=_date(_required(body, "period_start")),
            period_end=_date(_required(body, "period_end")),
            vat_rate=Decimal(body["vat_rate"]) if body.get("vat_rate") is not None else None,
            interest_cap_present=_required_bool(body, "interest_cap_present"),
        )
        return {
            "statement_id": issued.statement_id,
            "organisation_id": issued.organisation_id,
            "person_id": issued.person_id,
            "period_start": issued.period_start.isoformat(),
            "period_end": issued.period_end.isoformat(),
            "loans": issued.loans,
            "pdf_sha256": issued.pdf_sha256,
            "pdf_stubbed": True,
        }
    raise ServicingError("not-found", f"No route {method} {path}.", status=404)


def _agreement(record) -> dict:
    return {
        "agreement_id": record.agreement_id,
        "status": record.status,
        "organisation_id": record.organisation_id,
        "person_id": record.person_id,
        "booking_value_date": record.booking_value_date.isoformat(),
        "disbursement_value_date": record.disbursement_value_date.isoformat() if record.disbursement_value_date else None,
        "ledger_loan_id": record.ledger_loan_id,
        "frozen_full_name": record.frozen_full_name,
        "frozen_id_number": record.frozen_id_number,
        "frozen_service_address": record.frozen_service_address,
        "leniency_days": record.resolved.leniency_days,
        "annual_equivalent_rate": str(record.annual_equivalent_rate) if record.annual_equivalent_rate is not None else None,
    }


def _payment(payment) -> dict:
    return {
        "payment_id": payment.payment_id,
        "status": payment.status,
        "value_date": payment.value_date.isoformat(),
        "agreement_id": payment.agreement_id,
        "ledger_transaction_id": payment.ledger_transaction_id,
        "allocations": [{"bucket": bucket, "cents": cents} for bucket, cents in payment.allocations],
        "reversal_value_date": payment.reversal_value_date.isoformat() if payment.reversal_value_date else None,
    }


def _product(body: dict):
    code = body.get("product_code")
    if code not in _PRODUCTS:
        raise ServicingError("election-unset", "product_code must name a Day-1 template. No product is assumed.")
    return _PRODUCTS[code]()


def _settings(raw: dict) -> OrganisationSettings:
    def decimal(name: str):
        value = raw.get(name)
        return None if value is None else Decimal(str(value))

    return OrganisationSettings(
        leniency_days=raw.get("leniency_days"),
        full_payment_threshold_percent=decimal("full_payment_threshold_percent"),
        interest_on_deferred_initiation=raw.get("interest_on_deferred_initiation"),
        repo_rate_fall=raw.get("repo_rate_fall"),
        day_count_code=raw.get("day_count_code"),
        base_rate=decimal("base_rate"),
        discount_rate=decimal("discount_rate"),
        vat_on_rand_maxima=raw.get("vat_on_rand_maxima"),
        late_disbursement=raw.get("late_disbursement"),
        partial_prepayment=raw.get("partial_prepayment"),
    )


def _schedule(body: dict) -> tuple[tuple[date, int], ...]:
    rows = body.get("schedule")
    if not rows:
        raise ServicingError("schedule", "A schedule is required. Servicing does not build one.")
    return tuple((_date(due), int(amount)) for due, amount in rows)


def _required(body: dict, name: str):
    if body.get(name) is None:
        raise ServicingError("missing", f"{name} is required.")
    return body[name]


def _instant(body: dict, name: str) -> datetime:
    raw = _required(body, name)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ServicingError("value-date", "LOCKED_DECISIONS §1: a recognition timestamp must carry a timezone.")
    return parsed


def _optional_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    return _date(raw)


def _date(raw: str) -> date:
    return date.fromisoformat(raw)


def _required_bool(body: dict, name: str) -> bool:
    if name not in body or not isinstance(body[name], bool):
        raise ServicingError(
            "election-unset",
            "interest_cap_present must be supplied. Servicing does not assume a cap row exists.",
        )
    return body[name]
