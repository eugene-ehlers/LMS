"""HTTP-shaped contracts for early settlement. No session middleware."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lms.calc.models import RepoRate
from lms.settlement.errors import SettlementError
from lms.settlement.service import Settlement


def dispatch(
    settlement: Settlement,
    method: str,
    path: str,
    body: dict | None,
    headers: dict | None,
) -> tuple[int, dict]:
    body = body or {}
    headers = headers or {}
    try:
        return 200, _route(settlement, method.upper(), path, body, headers)
    except SettlementError as exc:
        return exc.status, {"success": False, "code": exc.code, "reason": str(exc)}


def _route(settlement: Settlement, method: str, path: str, body: dict, headers: dict) -> dict:
    parts = [part for part in path.split("/") if part]
    if (
        method == "POST"
        and len(parts) == 4
        and parts[:2] == ["v1", "agreements"]
        and parts[3] == "settlement-quotes"
    ):
        quoted = settlement.quote(
            agreement_id=parts[2],
            as_of=_date(_required(body, "as_of")),
            delivered_on=_date(_required(body, "delivered_on")),
            request_on=_date(_required(body, "request_on")),
            recognised_at=_instant(body, "recognised_at"),
            holidays=_holidays(body),
            interest_cap_present=_required_bool(body, "interest_cap_present"),
            vat_rate=_vat(body),
            repos=_repos(body),
        )
        return {
            "success": True,
            "confirmation": quoted.confirmation,
            "quote_id": quoted.quote_id,
            "agreement_id": quoted.agreement_id,
            "amount_owing_cents": quoted.amount_owing_cents,
            "valid_until": quoted.valid_until.isoformat(),
            "ncr_registration_number": quoted.ncr_registration_number,
            "early_termination_cents": quoted.early_termination_cents,
        }
    if (
        method == "POST"
        and len(parts) == 4
        and parts[:2] == ["v1", "agreements"]
        and parts[3] == "settlements"
    ):
        settled = settlement.execute(
            agreement_id=parts[2],
            quote_id=_required(body, "quote_id"),
            cents=_cents(body),
            recognised_at=_instant(body, "recognised_at"),
            interest_cap_present=_required_bool(body, "interest_cap_present"),
            vat_rate=_vat(body),
            idempotency_key=headers.get("Idempotency-Key", ""),
            repos=_repos(body),
        )
        return {
            "success": True,
            "confirmation": settled.confirmation,
            "agreement_id": settled.agreement_id,
            "quote_id": settled.quote_id,
            "amount_cents": settled.amount_cents,
            "balance_cents": settled.balance_cents,
            "ncr_registration_number": settled.ncr_registration_number,
        }
    raise SettlementError("not-found", f"No route {method} {path}.", status=404)


def _required(body: dict, name: str):
    if name not in body or body[name] is None:
        raise SettlementError("missing-field", f"Missing {name}.")
    return body[name]


def _required_bool(body: dict, name: str) -> bool:
    value = _required(body, name)
    if type(value) is not bool:
        raise SettlementError("missing-field", f"{name} must be true or false.")
    return value


def _cents(body: dict) -> int:
    raw = _required(body, "cents")
    if type(raw) is not int:
        raise SettlementError("cents", "Amounts are integer cents.")
    return raw


def _vat(body: dict) -> Decimal | None:
    if "vat_rate" not in body or body["vat_rate"] is None:
        return None
    raw = body["vat_rate"]
    if isinstance(raw, float) or type(raw) is not str:
        raise SettlementError(
            "vat-rate",
            "vat_rate must be a decimal string such as 0.15. A float is not accepted.",
        )
    try:
        return Decimal(raw)
    except Exception as exc:
        raise SettlementError("vat-rate", "vat_rate is not a decimal string.") from exc


def _date(raw: str) -> date:
    if type(raw) is not str:
        raise SettlementError("date", "A date must be an ISO calendar date.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise SettlementError("date", f"{raw} is not an ISO calendar date.") from exc


def _instant(body: dict, name: str) -> datetime:
    raw = _required(body, name)
    if type(raw) is not str:
        raise SettlementError("timestamp", f"{name} must be an ISO timestamp.")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SettlementError("timestamp", f"{name} is not an ISO timestamp.") from exc


def _holidays(body: dict) -> frozenset[date] | None:
    if "holidays" not in body or body["holidays"] is None:
        return None
    raw = body["holidays"]
    if not isinstance(raw, list):
        raise SettlementError("holidays-unset", "Public holidays were not supplied. No calendar is assumed.")
    return frozenset(_date(item) for item in raw)


def _repos(body: dict) -> tuple[RepoRate, ...]:
    raw = body.get("repos") or []
    if not isinstance(raw, list):
        raise SettlementError("repo", "repos must be a list of effective_from and annual_rate.")
    repos: list[RepoRate] = []
    for item in raw:
        if not isinstance(item, dict):
            raise SettlementError("repo", "Each repo row needs effective_from and annual_rate.")
        rate_raw = item.get("annual_rate")
        if type(rate_raw) is not str:
            raise SettlementError("repo", "Repo annual_rate must be a decimal string.")
        try:
            rate = Decimal(rate_raw)
        except Exception as exc:
            raise SettlementError("repo", "Repo annual_rate is not a decimal string.") from exc
        repos.append(RepoRate(_date(str(item.get("effective_from"))), rate))
    return tuple(repos)
