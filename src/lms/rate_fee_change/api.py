"""HTTP-shaped routes for a section 104 rate or fee change.

The notice document is not produced here. A collection campaign, a
restructure, and an early settlement are refused before any change is stored.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lms.ledger.errors import LedgerError
from lms.rate_fee_change.errors import RateFeeChangeError
from lms.rate_fee_change.models import Outcome
from lms.rate_fee_change.service import RateFeeChanges
from lms_config.exceptions import CalculationInputError

_RESTRUCTURE = {"contractual_end", "instalment_cents", "term_months", "term", "schedule", "payment_frequency"}
_OUT_OF_SCOPE = {
    "payment_holiday",
    "campaign_id",
    "settlement",
    "early_settlement",
    "quote_settlement",
    "rate_reduction",
    "fee_reductions",
}


def dispatch(
    changes: RateFeeChanges,
    method: str,
    path: str,
    body: dict | None,
    headers: dict | None,
) -> tuple[int, dict]:
    body = dict(body or {})
    headers = headers or {}
    try:
        _reject_shape(body)
        return _route(changes, method.upper(), path, body, headers)
    except RateFeeChangeError as exc:
        if not exc.audited:
            _record(changes, path, body, headers, exc)
        return exc.status, {"outcome": "failure", "code": exc.code, "message": str(exc)}
    except LedgerError as exc:
        return 422, {"outcome": "failure", "code": exc.code, "message": str(exc)}
    except CalculationInputError as exc:
        return 422, {"outcome": "failure", "code": "election-unset", "message": str(exc)}


def _route(
    changes: RateFeeChanges,
    method: str,
    path: str,
    body: dict,
    headers: dict,
) -> tuple[int, dict]:
    parts = [part for part in path.split("/") if part]
    actor = str(headers.get("X-Actor-Id", ""))
    if method == "POST" and _is(parts, "v1", "organisations", "*", "rate-fee-changes"):
        return _outcome(changes.apply(
            organisation_id=parts[2],
            actor_id=actor,
            recognised_at=_instant(body, "recognised_at"),
            notice_date=_optional_date(body, "notice_date"),
            effective_date=_optional_date(body, "effective_date"),
            end_date=_optional_date(body, "end_date"),
            periodic_rate=body.get("periodic_rate"),
            fees_cents=body.get("fees_cents"),
            fee_payment_frequency=body.get("fee_payment_frequency"),
            fee_payment_time=_optional_date(body, "fee_payment_time"),
            selector=_required(body, "selector"),
            loan_ids=_loan_ids(body),
            contractual_fees_cents=_contractual_fees(body),
            notice_business_days=body.get("notice_business_days"),
        ))
    if method == "POST" and _is(parts, "v1", "organisations", "*", "rate-fee-changes", "*", "end"):
        return _outcome(changes.end(
            organisation_id=parts[2],
            change_id=parts[4],
            actor_id=actor,
            recognised_at=_instant(body, "recognised_at"),
            end_date=_optional_date(body, "end_date"),
        ))
    if method in {"GET", "POST"} and _is(parts, "v1", "organisations", "*", "rate-fee-changes", "status"):
        report = changes.last_status(
            organisation_id=parts[2],
            on=_date(_required(body, "on"), "on"),
            loan_id=body.get("loan_id"),
        )
        return 200, _status(report)
    if method in {"GET", "POST"} and _is(
        parts, "v1", "organisations", "*", "loans", "*", "rate-fee-change-status"
    ):
        report = changes.last_status(
            organisation_id=parts[2],
            on=_date(_required(body, "on"), "on"),
            loan_id=parts[4],
        )
        return 200, _status(report)
    if method == "POST" and _is(parts, "v1", "organisations", "*", "loans", "*", "rate-fee-accruals"):
        accrual = changes.accrue(
            organisation_id=parts[2],
            loan_id=parts[4],
            recognised_at=_instant(body, "recognised_at"),
            interest_cap_present=_required_bool(body, "interest_cap_present"),
        )
        return 200, {
            "outcome": "success",
            "confirmation": (
                f"Interest for {accrual.value_date.isoformat()} was accrued at periodic rate "
                f"{accrual.periodic_rate} at 00:00 Africa/Johannesburg."
            ),
            "loan_id": accrual.loan_id,
            "value_date": accrual.value_date.isoformat(),
            "periodic_rate": str(accrual.periodic_rate),
            "day_rands": str(accrual.day_rands),
        }
    if method == "POST" and _is(parts, "v1", "organisations", "*", "loans", "*", "rate-fee-service-fees"):
        transaction = changes.levy_service_fee(
            organisation_id=parts[2],
            loan_id=parts[4],
            recognised_at=_instant(body, "recognised_at"),
            monthly_cents=_cents(_required(body, "monthly_cents"), "monthly_cents"),
            due_on=_date(_required(body, "due_on"), "due_on"),
            interest_cap_present=_required_bool(body, "interest_cap_present"),
            vat_rate=_optional_decimal(body.get("vat_rate")),
            vat_registered=body.get("vat_registered", True),
            opening=bool(body.get("opening", False)),
            first_due=_optional_date(body, "first_due"),
        )
        return 200, {
            "outcome": "success",
            "confirmation": (
                f"Service fee levied for {parts[4]} on {transaction.value_date.isoformat()} "
                "at 00:00 Africa/Johannesburg."
            ),
            "transaction_id": transaction.transaction_id,
            "amount_cents": transaction.amount_cents,
        }
    if method == "POST" and _is(parts, "v1", "organisations", "*", "loans", "*", "rate-fee-charges"):
        transaction = changes.levy_charge(
            organisation_id=parts[2],
            loan_id=parts[4],
            bucket=_required(body, "bucket"),
            cents=_cents(_required(body, "cents"), "cents"),
            due_on=_date(_required(body, "due_on"), "due_on"),
            recognised_at=_instant(body, "recognised_at"),
            interest_cap_present=_required_bool(body, "interest_cap_present"),
        )
        return 200, {
            "outcome": "success",
            "confirmation": (
                f"Charge levied for {parts[4]} on {transaction.value_date.isoformat()} "
                "at 00:00 Africa/Johannesburg."
            ),
            "transaction_id": transaction.transaction_id,
            "amount_cents": transaction.amount_cents,
        }
    raise RateFeeChangeError("route", f"No rate or fee route matches {method} {path}.")


def _record(changes: RateFeeChanges, path: str, body: dict, headers: dict, exc: RateFeeChangeError) -> None:
    parts = [part for part in path.split("/") if part]
    organisation_id = parts[2] if len(parts) > 2 and parts[:2] == ["v1", "organisations"] else ""
    recognised_at = None
    raw = body.get("recognised_at")
    if isinstance(raw, datetime) and raw.tzinfo is not None:
        recognised_at = raw
    elif isinstance(raw, str):
        try:
            recognised_at = _instant(body, "recognised_at")
        except RateFeeChangeError:
            recognised_at = None
    changes.record_failure(
        organisation_id=organisation_id,
        actor_id=str(headers.get("X-Actor-Id", "")),
        recognised_at=recognised_at,
        code=exc.code,
        message=str(exc),
        loan_ids=exc.loan_ids,
    )


def _outcome(outcome: Outcome) -> tuple[int, dict]:
    body = {
        "outcome": "success" if outcome.ok else "failure",
        "code": outcome.code,
        "message": outcome.message,
        "change_id": outcome.change_id,
        "loan_ids": list(outcome.loan_ids),
        "notice_date": None if outcome.notice_date is None else outcome.notice_date.isoformat(),
        "effective_date": None if outcome.effective_date is None else outcome.effective_date.isoformat(),
        "end_date": None if outcome.end_date is None else outcome.end_date.isoformat(),
        "recognition_date": (
            None if outcome.recognition_date is None else outcome.recognition_date.isoformat()
        ),
    }
    if outcome.ok:
        body["confirmation"] = outcome.message
    return outcome.status, body


def _status(report) -> dict:
    return {
        "query": "success",
        "found": report.found,
        "outcome": report.outcome,
        "code": report.code,
        "message": report.message,
        "action": report.action,
        "change_id": report.change_id,
        "loan_ids": list(report.loan_ids),
        "occurred_at": None if report.occurred_at is None else report.occurred_at.isoformat(),
        "recognition_date": (
            None if report.recognition_date is None else report.recognition_date.isoformat()
        ),
    }


def _reject_shape(body: dict) -> None:
    restructure = _RESTRUCTURE.intersection(body)
    if restructure:
        names = ", ".join(sorted(restructure))
        raise RateFeeChangeError(
            "restructure",
            "Changing the contractual term or the contractual instalment is a restructure. "
            f"This action does not accept {names}.",
        )
    outside = _OUT_OF_SCOPE.intersection(body)
    if outside:
        names = ", ".join(sorted(outside))
        raise RateFeeChangeError(
            "out-of-scope",
            "A payment holiday, collection campaign, or early settlement is not a section 104 "
            f"rate or fee change. This action does not accept {names}.",
        )


def _is(parts: list[str], *pattern: str) -> bool:
    if len(parts) != len(pattern):
        return False
    return all(left == right or right == "*" for left, right in zip(parts, pattern))


def _required(body: dict, key: str):
    if key not in body or body[key] is None:
        raise RateFeeChangeError(
            "field-missing",
            f"{key} is required. Nothing was applied.",
        )
    return body[key]


def _required_bool(body: dict, key: str) -> bool:
    value = _required(body, key)
    if not isinstance(value, bool):
        raise RateFeeChangeError(
            "field-missing",
            f"{key} must be true or false. Nothing was applied.",
        )
    return value


def _instant(body: dict, key: str) -> datetime:
    value = _required(body, key)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise RateFeeChangeError(
                "timestamp-naive",
                "Recognition time must carry a time zone. The recognition date is "
                "00:00 Africa/Johannesburg. The change was not applied.",
            ) from exc
    else:
        raise RateFeeChangeError(
            "timestamp-naive",
            "Recognition time must carry a time zone. The recognition date is "
            "00:00 Africa/Johannesburg. The change was not applied.",
        )
    if parsed.tzinfo is None:
        raise RateFeeChangeError(
            "timestamp-naive",
            "Recognition time must carry a time zone. The recognition date is "
            "00:00 Africa/Johannesburg. The change was not applied.",
        )
    return parsed


def _optional_date(body: dict, key: str) -> date | None:
    if key not in body or body[key] is None:
        return None
    return _date(body[key], key)


def _date(value, key: str) -> date:
    if isinstance(value, datetime) or (isinstance(value, str) and "T" in value):
        raise RateFeeChangeError(
            "payment-time" if key == "fee_payment_time" else "date",
            f"{key} is a Johannesburg calendar date, not a clock time. "
            "Recognition is 00:00 Africa/Johannesburg. Nothing was applied.",
        )
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise RateFeeChangeError(
            "date",
            f"{key} must be a calendar date. Nothing was applied.",
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RateFeeChangeError(
            "date",
            f"{key} must be a calendar date. Nothing was applied.",
        ) from exc


def _loan_ids(body: dict) -> tuple[str, ...]:
    raw = body.get("loan_ids")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise RateFeeChangeError(
            "loan-unknown",
            "loan_ids must be a list of loan ids. Nothing was applied.",
        )
    return tuple(raw)


def _contractual_fees(body: dict) -> dict[str, dict[str, int]]:
    raw = body.get("contractual_fees_cents")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RateFeeChangeError(
            "fee",
            "contractual_fees_cents is a map of loan id to fee amounts in integer cents. "
            "Nothing was applied.",
        )
    parsed: dict[str, dict[str, int]] = {}
    for loan_id, fees in raw.items():
        if not isinstance(loan_id, str) or not isinstance(fees, dict):
            raise RateFeeChangeError(
                "fee",
                "contractual_fees_cents is a map of loan id to fee amounts in integer cents. "
                "Nothing was applied.",
            )
        parsed[loan_id] = {str(key): _cents(amount, str(key)) for key, amount in fees.items()}
    return parsed


def _cents(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RateFeeChangeError(
            "fee-cents",
            f"{label} must be an integer number of cents. Nothing was applied.",
        )
    return value


def _optional_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, float):
        raise RateFeeChangeError(
            "rate",
            "vat_rate must be a decimal string, not a float. Nothing was applied.",
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    raise RateFeeChangeError(
        "rate",
        "vat_rate must be a decimal string. Nothing was applied.",
    )
