"""Servicing.book stores the decision-engine application number and credit-life premium."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from lms.dummies.fixtures import FIXED_CREDIT_LIFE_PREMIUM_CENTS
from lms.servicing.api import dispatch
from lms.servicing.errors import ServicingError
from lms.stubs.decision_quote import DecisionQuoteStub
from lms.stubs.wire import book_quoted
from lms_config.calendar import value_instant
from tests.test_quote_stub import request
from tests.test_servicing import book, servicing


def test_a_missing_application_number_is_not_stored() -> None:
    svc = servicing()
    record = book(svc, application_number="APP-42")
    assert record.application_number == "APP-42"
    assert svc.agreements[record.agreement_id].application_number == "APP-42"

    for missing in (None, "", "   "):
        fresh = servicing()
        with pytest.raises(ServicingError) as raised:
            book(fresh, key="missing-number", application_number=missing)
        assert raised.value.code == "application-number"
        assert fresh.agreements == {}


def test_a_missing_credit_life_premium_is_zero_and_a_negative_is_refused() -> None:
    svc = servicing()
    omitted = book(svc, key="omit-premium", application_number="APP-1")
    explicit_zero = book(svc, key="zero-premium", application_number="APP-2", credit_life_premium_cents=0)
    stated = book(svc, key="stated-premium", application_number="APP-3", credit_life_premium_cents=199)
    assert omitted.credit_life_premium_cents == 0
    assert explicit_zero.credit_life_premium_cents == 0
    assert stated.credit_life_premium_cents == 199
    assert svc.agreements[stated.agreement_id].credit_life_premium_cents == 199

    fresh = servicing()
    with pytest.raises(ServicingError) as negative:
        book(fresh, key="negative-premium", application_number="APP-4", credit_life_premium_cents=-1)
    assert negative.value.code == "credit-life-premium"
    with pytest.raises(ServicingError) as fractional:
        book(fresh, key="fractional-premium", application_number="APP-5", credit_life_premium_cents=1.5)  # type: ignore[arg-type]
    assert fractional.value.code == "credit-life-premium"
    with pytest.raises(ServicingError) as boolean:
        book(fresh, key="boolean-premium", application_number="APP-6", credit_life_premium_cents=True)  # type: ignore[arg-type]
    assert boolean.value.code == "credit-life-premium"
    assert fresh.agreements == {}


def test_the_existing_agreement_route_stores_both_fields() -> None:
    svc = servicing()
    body = {
        "organisation_id": "org-a",
        "person_id": "person-a",
        "product_code": "micro_short_term",
        "recognised_at": "2026-03-01T08:00:00+02:00",
        "cash_advanced_cents": 100_000,
        "frequency": "monthly",
        "schedule": [["2026-06-15", 100_000]],
        "application_number": "APP-HTTP",
        "settings": {
            "leniency_days": 1,
            "full_payment_threshold_percent": "100",
            "interest_on_deferred_initiation": "none",
            "repo_rate_fall": "contract_rate",
            "day_count_code": "actual_actual",
            "vat_on_rand_maxima": "exclusive",
            "late_disbursement": "keep_instalment",
            "partial_prepayment": "shorten_term",
            "in_duplum_trigger": "collections_default",
        },
    }
    status, payload = dispatch(svc, "POST", "/v1/agreements", body, {"Idempotency-Key": "http-store"})
    assert status == 200
    assert payload["application_number"] == "APP-HTTP"
    assert payload["credit_life_premium_cents"] == 0
    stored = svc.agreements[payload["agreement_id"]]
    assert stored.application_number == "APP-HTTP"
    assert stored.credit_life_premium_cents == 0

    missing = dict(body)
    missing.pop("application_number")
    status, rejected = dispatch(svc, "POST", "/v1/agreements", missing, {"Idempotency-Key": "http-missing"})
    assert status == 422
    assert rejected["code"] == "application-number"

    negative = dict(body)
    negative["application_number"] = "APP-HTTP-NEG"
    negative["credit_life_premium_cents"] = -5
    status, rejected = dispatch(svc, "POST", "/v1/agreements", negative, {"Idempotency-Key": "http-negative"})
    assert status == 422
    assert rejected["code"] == "credit-life-premium"
    assert set(svc.agreements) == {payload["agreement_id"]}


def test_the_quote_wire_passes_the_number_and_premium_into_book() -> None:
    approval = DecisionQuoteStub().quote(request())
    payload = approval.book_payload()
    assert approval.credit_life_premium_cents == FIXED_CREDIT_LIFE_PREMIUM_CENTS
    assert payload["application_number"] == approval.application_number
    assert payload["credit_life_premium_cents"] == approval.credit_life_premium_cents

    record = book_quoted(servicing(), approval)

    assert record.application_number == approval.application_number
    assert record.credit_life_premium_cents == FIXED_CREDIT_LIFE_PREMIUM_CENTS
    assert record.recognised_at == value_instant(date(2026, 3, 1))
    recognised = record.recognised_at.astimezone(ZoneInfo("Africa/Johannesburg"))
    assert (recognised.hour, recognised.minute, recognised.second) == (0, 0, 0)
    assert record.booking_value_date == date(2026, 3, 1)
