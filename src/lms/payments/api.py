"""Receipt intake and debit-order routes. No session middleware and no bank socket."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lms.payments.errors import PaymentRailError
from lms.payments.models import InboundReceipt, RailReceipt
from lms.payments.rail import PaymentRail
from lms_config.exceptions import CalculationInputError


def dispatch(rail: PaymentRail, method: str, path: str, body: dict | None, headers: dict | None) -> tuple[int, dict]:
    body = body or {}
    headers = headers or {}
    try:
        return 200, _route(rail, method.upper(), path, body, headers)
    except PaymentRailError as exc:
        return exc.status, {"code": exc.code, "message": str(exc)}
    except CalculationInputError as exc:
        return 422, {"code": "election-unset", "message": str(exc)}


def _route(rail: PaymentRail, method: str, path: str, body: dict, headers: dict) -> dict:
    parts = [part for part in path.split("/") if part]
    if method == "POST" and parts == ["v1", "payment-rails", "loan-numbers"]:
        number = rail.register_loan_number(
            organisation_id=_required(body, "organisation_id"),
            agreement_id=_required(body, "agreement_id"),
            application_number=_required(body, "application_number"),
            recognised_at=_instant(body, "recognised_at"),
            actor_id=_required(body, "actor_id"),
            laybye=bool(body.get("laybye") or False),
        )
        return {"loan_number": number}
    if method == "POST" and parts == ["v1", "payment-rails", "debit-orders"]:
        produced = rail.generate_debit_order_file(
            organisation_id=_required(body, "organisation_id"),
            due_on=_date(_required(body, "due_on")),
            recognised_at=_instant(body, "recognised_at"),
            actor_id=_required(body, "actor_id"),
            agreement_ids=tuple(body.get("agreement_ids") or ()),
            idempotency_key=headers.get("Idempotency-Key", ""),
            interest_cap_present=body.get("interest_cap_present"),
            vat_rate=_optional_decimal(body.get("vat_rate")),
        )
        return _file(produced)
    if method == "POST" and parts == ["v1", "payment-rails", "receipts"]:
        accepted = rail.accept_receipts(
            _required(body, "organisation_id"),
            tuple(_inbound(item) for item in body.get("receipts") or ()),
            actor_id=_required(body, "actor_id"),
            interest_cap_present=body.get("interest_cap_present"),
            vat_rate=_optional_decimal(body.get("vat_rate")),
        )
        return {"receipts": [_receipt(item) for item in accepted]}
    if method == "POST" and parts == ["v1", "payment-rails", "receipts", "intake"]:
        accepted = rail.intake_from_rail(
            _required(body, "organisation_id"),
            actor_id=_required(body, "actor_id"),
            interest_cap_present=body.get("interest_cap_present"),
            vat_rate=_optional_decimal(body.get("vat_rate")),
        )
        return {"receipts": [_receipt(item) for item in accepted]}
    if method == "POST" and len(parts) == 5 and parts[:3] == ["v1", "payment-rails", "receipts"] and parts[4] == "match":
        receipt = rail.match_receipt(
            parts[3],
            actor_id=_required(body, "actor_id"),
            interest_cap_present=body.get("interest_cap_present"),
            vat_rate=_optional_decimal(body.get("vat_rate")),
            loan_number=body.get("loan_number"),
            id_number=body.get("id_number"),
            attributed_due_on=_optional_date(body.get("attributed_due_on")),
        )
        return _receipt(receipt)
    if method == "POST" and len(parts) == 5 and parts[:3] == ["v1", "payment-rails", "receipts"] and parts[4] == "returns":
        receipt = rail.return_unpaid(
            parts[3],
            recognised_at=_instant(body, "recognised_at"),
            actor_id=_required(body, "actor_id"),
        )
        return _receipt(receipt)
    raise PaymentRailError("not-found", f"No route {method} {path}.", status=404)


def _inbound(item: dict) -> InboundReceipt:
    return InboundReceipt(
        amount_cents=int(_required(item, "amount_cents")),
        recognised_at=_instant(item, "recognised_at"),
        purpose=item.get("purpose"),
        loan_number=item.get("loan_number"),
        id_number=item.get("id_number"),
        agreement_id=item.get("agreement_id"),
        attributed_due_on=_optional_date(item.get("attributed_due_on")),
        idempotency_key=str(item.get("idempotency_key") or ""),
    )


def _file(produced) -> dict:
    return {
        "submission_id": produced.submission_id,
        "organisation_id": produced.organisation_id,
        "recognition_date": produced.recognition_date.isoformat(),
        "due_on": produced.due_on.isoformat(),
        "body": produced.body,
        "instructions": [
            {
                "loan_number": item.loan_number,
                "amount_cents": item.amount_cents,
                "due_on": item.due_on.isoformat(),
                "recognition_date": item.recognition_date.isoformat(),
                "credit_life_premium_cents": item.credit_life_premium_cents,
                "purpose": item.purpose,
                "scheme": item.scheme,
                "agreement_id": item.agreement_id,
                "application_number": item.application_number,
                "mandate_reference": item.mandate_reference,
                "tracking_indicator": item.tracking_indicator,
            }
            for item in produced.instructions
        ],
    }


def _receipt(receipt: RailReceipt) -> dict:
    return {
        "receipt_id": receipt.receipt_id,
        "organisation_id": receipt.organisation_id,
        "amount_cents": receipt.amount_cents,
        "recognised_at": receipt.recognised_at.isoformat(),
        "value_date": receipt.value_date.isoformat(),
        "sequence": receipt.sequence,
        "status": receipt.status,
        "purpose": receipt.purpose,
        "loan_number": receipt.loan_number,
        "agreement_id": receipt.agreement_id,
        "attributed_due_on": None if receipt.attributed_due_on is None else receipt.attributed_due_on.isoformat(),
        "ledger_transaction_id": receipt.ledger_transaction_id,
        "allocations": [{"bucket": bucket, "cents": cents} for bucket, cents in receipt.allocations],
        "flag": receipt.flag,
    }


def _required(body: dict, name: str):
    if name not in body or body[name] is None:
        raise PaymentRailError("missing", f"{name} is required.")
    return body[name]


def _instant(body: dict, name: str) -> datetime:
    raw = _required(body, name)
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise PaymentRailError("timestamp", f"{name} is not an ISO timestamp.") from exc


def _date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PaymentRailError("date", "A date must be YYYY-MM-DD.") from exc


def _optional_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    return _date(raw)


def _optional_decimal(raw) -> Decimal | None:
    if raw is None:
        return None
    return Decimal(str(raw))
