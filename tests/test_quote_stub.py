"""The quote stub returns a Servicing.book payload and stays inside the statutory cap."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from lms.dummies.fixtures import FIXED_CREDIT_LIFE_PREMIUM_CENTS
from lms.servicing.api import dispatch
from lms.stubs.decision_quote import DecisionQuoteStub, QuoteRequest, QuoteStubError
from lms.stubs.wire import book_quoted
from lms_config.calendar import value_instant
from lms_config.statute import SHORT_TERM_FIRST_MONTHLY, UNSECURED_REPO_MARGIN
from lms_config.templates import micro_short_term, unsecured_personal
from tests.test_servicing import DUE, at, servicing, settings


def request(**overrides) -> QuoteRequest:
    values = dict(
        organisation_id="org-a",
        person_id="person-a",
        product=micro_short_term(),
        settings=settings(),
        recognised_at=at(1, 15),
        cash_advanced_cents=100_000,
        frequency="monthly",
        schedule=((DUE, 100_000),),
        idempotency_key="quote-1",
        initiation_fee_cents=0,
    )
    values.update(overrides)
    return QuoteRequest(**values)


def test_quote_approval_books_through_the_existing_method() -> None:
    stub = DecisionQuoteStub()
    first = stub.quote(request())
    second = stub.quote(request(idempotency_key="quote-2"))
    svc = servicing()

    record = book_quoted(svc, first)

    assert first.approved is True
    assert first.contractual_rate == Decimal("0.05")
    assert first.contractual_rate <= SHORT_TERM_FIRST_MONTHLY
    assert first.credit_life_premium_cents == FIXED_CREDIT_LIFE_PREMIUM_CENTS
    assert first.application_number == "APP-00000001"
    assert second.application_number == "APP-00000002"
    assert first.application_number != second.application_number
    assert first.recognised_at == value_instant(date(2026, 3, 1))
    assert record.agreement_id in svc.agreements
    assert record.application_number == first.application_number
    assert record.rate_supplied_by_decision_engine is True
    assert record.short_term_rate_cap == SHORT_TERM_FIRST_MONTHLY
    assert record.product.instruments[0].monthly_rate == first.contractual_rate
    assert record.recognised_at == first.recognised_at
    assert record.cash_advanced_cents == 100_000
    status, body = dispatch(svc, "POST", "/v1/quotes", {}, {})
    assert status == 404
    assert body["code"] == "not-found"


def test_a_rate_above_the_short_term_cap_is_not_an_approval() -> None:
    product = micro_short_term()
    credit = replace(
        product.instruments[0],
        monthly_rate=Decimal("0.06"),
        base_rate=Decimal("0.06"),
    )
    stub = DecisionQuoteStub()

    with pytest.raises(QuoteStubError):
        stub.quote(request(product=replace(product, instruments=(credit,))))

    assert stub.quote(request(idempotency_key="still-first")).application_number == "APP-00000001"


def test_unsecured_template_rate_is_inside_the_repo_margin() -> None:
    approval = DecisionQuoteStub().quote(
        request(product=unsecured_personal(), idempotency_key="unsecured")
    )

    assert approval.contractual_rate == UNSECURED_REPO_MARGIN
    assert approval.contractual_rate <= UNSECURED_REPO_MARGIN
    assert approval.short_term_rate_cap is None


def test_unsecured_rate_above_the_margin_is_refused() -> None:
    product = unsecured_personal()
    credit = replace(
        product.instruments[0],
        base_rate=Decimal("0.22"),
        repo_margin=Decimal("0.22"),
    )

    with pytest.raises(QuoteStubError):
        DecisionQuoteStub().quote(request(product=replace(product, instruments=(credit,))))


def test_amounts_must_be_integer_cents() -> None:
    with pytest.raises(QuoteStubError):
        DecisionQuoteStub().quote(request(cash_advanced_cents=100.0))  # type: ignore[arg-type]
    with pytest.raises(QuoteStubError):
        DecisionQuoteStub().quote(request(cash_advanced_cents=True))  # type: ignore[arg-type]
