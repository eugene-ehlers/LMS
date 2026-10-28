"""HTTP-shaped routes for collection campaigns. No session middleware.

The notice document and the debit-order file are not produced here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lms.collection_campaigns.errors import CollectionCampaignError
from lms.collection_campaigns.models import NOTICE_BUSINESS_DAYS
from lms.collection_campaigns.service import CollectionCampaigns
from lms.ledger.errors import LedgerError
from lms_config.exceptions import CalculationInputError

_RESTRUCTURE = {"contractual_end", "instalment_cents", "term_months", "term", "schedule"}


def dispatch(
    campaigns: CollectionCampaigns,
    method: str,
    path: str,
    body: dict | None,
    headers: dict | None,
) -> tuple[int, dict]:
    body = dict(body or {})
    headers = headers or {}
    try:
        _reject_restructure(body)
        return 200, _route(campaigns, method.upper(), path, body, headers)
    except CollectionCampaignError as exc:
        return exc.status, {"code": exc.code, "message": str(exc)}
    except LedgerError as exc:
        return 422, {"code": exc.code, "message": str(exc)}
    except CalculationInputError as exc:
        return 422, {"code": "election-unset", "message": str(exc)}


def _route(
    campaigns: CollectionCampaigns,
    method: str,
    path: str,
    body: dict,
    headers: dict,
) -> dict:
    parts = [part for part in path.split("/") if part]
    actor = headers.get("X-Actor-Id", "")
    if method == "POST" and parts == ["v1", "collection-campaigns"]:
        campaign = campaigns.create(
            organisation_id=_required(body, "organisation_id"),
            actor_id=actor,
            recognised_at=_instant(body, "recognised_at"),
            start_date=_date(_required(body, "start_date")),
            end_date=_optional_date(body.get("end_date")),
            rate_reduction=_rate(body, "rate_reduction"),
            fee_reductions=_fee_map(_required(body, "fee_reductions")),
            payment_holiday=_required_bool(body, "payment_holiday"),
            notice_date=_date(_required(body, "notice_date")),
        )
        return _campaign(campaign)
    if method == "POST" and len(parts) == 3 and parts[:2] == ["v1", "collection-campaigns"]:
        campaign = campaigns.edit(
            parts[2],
            organisation_id=_required(body, "organisation_id"),
            actor_id=actor,
            recognised_at=_instant(body, "recognised_at"),
            start_date=_date(_required(body, "start_date")),
            end_date=_optional_date(body.get("end_date")),
            rate_reduction=_rate(body, "rate_reduction"),
            fee_reductions=_fee_map(_required(body, "fee_reductions")),
            payment_holiday=_required_bool(body, "payment_holiday"),
            notice_date=_date(_required(body, "notice_date")),
        )
        return _campaign(campaign)
    if (
        method == "POST"
        and len(parts) == 4
        and parts[:2] == ["v1", "collection-campaigns"]
        and parts[3] == "end"
    ):
        campaign = campaigns.end(
            parts[2],
            organisation_id=_required(body, "organisation_id"),
            actor_id=actor,
            recognised_at=_instant(body, "recognised_at"),
            end_date=_date(_required(body, "end_date")),
        )
        return _campaign(campaign)
    if (
        method == "POST"
        and len(parts) == 6
        and parts[0] == "v1"
        and parts[1] == "organisations"
        and parts[3] == "loans"
        and parts[5] == "registration"
    ):
        registered = campaigns.register_account(
            organisation_id=parts[2],
            loan_id=parts[4],
            product_code=_required(body, "product_code"),
            contractual_fees_cents=_fee_map(_required(body, "contractual_fees_cents")),
            actor_id=actor,
        )
        return {
            "organisation_id": registered.organisation_id,
            "loan_id": registered.loan_id,
            "product_code": registered.product_code,
            "contractual_fees_cents": dict(registered.contractual_fees_cents),
        }
    if (
        method == "POST"
        and len(parts) == 6
        and parts[0] == "v1"
        and parts[1] == "organisations"
        and parts[3] == "collection-campaigns"
        and parts[5] == "applications"
    ):
        loan_ids = body.get("loan_ids")
        if loan_ids is not None and (
            isinstance(loan_ids, str) or not isinstance(loan_ids, list)
        ):
            raise CollectionCampaignError("loan-list", "loan_ids is a list of ledger loan ids.")
        applications = campaigns.apply(
            parts[4],
            organisation_id=parts[2],
            actor_id=actor,
            recognised_at=_instant(body, "recognised_at"),
            selector=_required(body, "selector"),
            product_code=body.get("product_code"),
            loan_ids=None if loan_ids is None else tuple(loan_ids),
        )
        return {
            "campaign_id": parts[4],
            "organisation_id": parts[2],
            "loan_ids": [item.loan_id for item in applications],
            "count": len(applications),
        }
    if (
        method == "POST"
        and len(parts) == 6
        and parts[0] == "v1"
        and parts[1] == "organisations"
        and parts[3] == "loans"
        and parts[5] == "collection-campaign-accruals"
    ):
        accrual = campaigns.accrue(
            organisation_id=parts[2],
            loan_id=parts[4],
            recognised_at=_instant(body, "recognised_at"),
            interest_cap_present=_required_bool(body, "interest_cap_present"),
        )
        return {
            "loan_id": accrual.loan_id,
            "value_date": accrual.value_date.isoformat(),
            "periodic_rate": format(accrual.periodic_rate, "f"),
            "base_cents": accrual.base_cents,
            "day_rands": format(accrual.day_rands, "f"),
        }
    raise CollectionCampaignError("not-found", f"No route {method} {path}.", status=404)


def _campaign(campaign) -> dict:
    return {
        "campaign_id": campaign.campaign_id,
        "organisation_id": campaign.organisation_id,
        "start_date": campaign.start_date.isoformat(),
        "end_date": None if campaign.end_date is None else campaign.end_date.isoformat(),
        "rate_reduction": format(campaign.rate_reduction, "f"),
        "fee_reductions_cents": dict(campaign.fee_reductions),
        "payment_holiday": campaign.payment_holiday,
        "notice_date": campaign.notice_date.isoformat(),
        "notice_business_days": NOTICE_BUSINESS_DAYS,
        "open_ended": campaign.end_date is None,
    }


def _reject_restructure(body: dict) -> None:
    present = _RESTRUCTURE.intersection(body)
    if present:
        names = ", ".join(sorted(present))
        raise CollectionCampaignError(
            "restructure",
            f"A change to the contractual term or instalment is a restructure, not a collection campaign ({names}).",
        )
    if "notice_business_days" in body and body["notice_business_days"] != NOTICE_BUSINESS_DAYS:
        raise CollectionCampaignError(
            "notice-fixed",
            "Section 104(2) notice is five business days. The LMS records that interval and does not take another.",
        )


def _required(body: dict, name: str):
    if name not in body or body[name] in (None, ""):
        raise CollectionCampaignError("field-unset", f"{name} is required.")
    return body[name]


def _required_bool(body: dict, name: str) -> bool:
    if name not in body or not isinstance(body[name], bool):
        raise CollectionCampaignError("field-unset", f"{name} is required.")
    return body[name]


def _rate(body: dict, name: str) -> Decimal:
    raw = _required(body, name)
    if isinstance(raw, float) or isinstance(raw, bool):
        raise CollectionCampaignError("rate", "A rate reduction is a decimal string, not a float.")
    if isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str):
        raise CollectionCampaignError("rate", "A rate reduction is a decimal string.")
    try:
        return Decimal(raw)
    except Exception as exc:
        raise CollectionCampaignError("rate", "A rate reduction is a decimal string.") from exc


def _fee_map(raw: dict) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise CollectionCampaignError("fee", "Fee amounts are a map of fee type to integer cents.")
    cleaned: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise CollectionCampaignError("fee", "A fee amount is an integer number of cents.")
        cleaned[str(key)] = value
    return cleaned


def _instant(body: dict, name: str) -> datetime:
    raw = _required(body, name)
    if not isinstance(raw, str):
        raise CollectionCampaignError("timestamp", f"{name} is an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CollectionCampaignError("timestamp", f"{name} is an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise CollectionCampaignError(
            "timestamp-naive",
            "Decision 1: a timestamp must carry a zone so the Johannesburg recognition date is known.",
        )
    return parsed


def _date(raw: str) -> date:
    if not isinstance(raw, str):
        raise CollectionCampaignError("date", "A date is YYYY-MM-DD.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise CollectionCampaignError("date", "A date is YYYY-MM-DD.") from exc


def _optional_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    return _date(raw)
