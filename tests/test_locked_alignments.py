"""Alignments with docs/LOCKED_DECISIONS.md. Figures are pinned, not hand-rounded."""

from datetime import date
from decimal import Decimal

import pytest

from lms.calc.examples import (
    VAT_15,
    example_campaign_and_zeros,
    example_fresh_duplum_ceiling,
    example_laybye_net_interest,
    example_leniency_and_threshold,
)
from lms.calc.interest import campaign_terms
from lms.calc.ledger import run
from lms.calc.models import Agreement, Payment, Policy, Product, RepoFallChoice, RepoRate
from lms.calc.money import RuleError


def test_second_default_gets_a_fresh_ceiling():
    assert example_fresh_duplum_ceiling() == {
        "episode1_ceiling": 20_000,
        "episode1_accrued": 20_000,
        "episode1_closed_month": 9,
        "episode1_closed_day": 15,
        "principal_after_cure": 5_000,
        "cured_in_default": 0,
        "episode2_ceiling": 5_000,
        "episode2_started_month": 10,
        "episode2_started_day": 1,
        "fresh_episode2_accrued": 5_000,
        "aggregate_episode2_accrued": 0,
        "aggregate_episode2_ceiling": 5_000,
        "fresh_october_interest": 250,
        "fresh_october_service": 4_750,
        "aggregate_october_interest": 0,
        "aggregate_october_service": 0,
    }


def test_leniency_flag_and_interest_that_keeps_accruing():
    assert example_leniency_and_threshold() == {
        "april3_in_default": 0,
        "april3_unbilled_interest": 500,
        "april4_in_default": 1,
        "april30_interest_leniency_4": 10_000,
        "april30_interest_leniency_1": 10_000,
        "bundle": 111_677,
        "pay_95": 106_094,
        "pay_95_in_default": 0,
        "pay_95_principal_left": 5_583,
        "pay_short_in_default": 1,
    }


def test_leniency_zero_flags_on_the_due_date():
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 3, 1),
        maturity_date=date(2026, 6, 30),
        initiation_paid_upfront=True,
        principal_instalments=((date(2026, 3, 31), 100_000),),
    )
    from lms.calc.fees import initiation_fee
    from lms.calc.models import FeeCapBasis

    fee = initiation_fee(
        100_000, on=date(2026, 3, 1), vat_rates=VAT_15, basis=FeeCapBasis.EXCLUSIVE
    )[2]
    opened = (Payment(date(2026, 3, 1), fee, purpose="initiation_upfront"),)
    on_due = run(
        agreement,
        opened,
        until=date(2026, 3, 31),
        policy=Policy(leniency_days=0, full_payment_threshold_percent=Decimal("100")),
        vat_rates=VAT_15,
    ).state
    day_after = run(
        agreement,
        opened,
        until=date(2026, 3, 31),
        policy=Policy(leniency_days=1, full_payment_threshold_percent=Decimal("100")),
        vat_rates=VAT_15,
    ).state
    assert on_due.in_default is True
    assert day_after.in_default is False


def test_laybye_net_balance_and_one_service_fee():
    assert example_laybye_net_interest() == {
        "gross_interest": 5_000,
        "net_interest": 3_000,
        "service_fee": 6_900,
        "service_count": 1,
        "gross_service_fee": 6_900,
        "covered_interest": 0,
        "covered_service_count": 1,
        "covered_service_fee": 6_900,
        "duplum_ceiling": 100_000,
        "stepped_interest": 1_452,
        "stepped_service_count": 1,
    }


def test_zero_rates_fees_and_campaign_discount():
    assert example_campaign_and_zeros() == {
        "march_interest": 0,
        "march_service": 0,
        "march_initiation": 0,
        "april_interest": 5_000,
        "april_service": 0,
        "april_in_default": 1,
        "leniency_april3_in_default": 0,
        "leniency_april3_unbilled": 0,
        "leniency_april_interest": 4_500,
        "sticky_april_interest": 0,
        "sticky_april_in_default": 1,
        "quote_total": 100_000,
        "literal_interest": 0,
        "literal_service": 0,
        "literal_initiation": 0,
        "literal_quote": 100_000,
        "base_bps": 500,
        "discount_bps": 500,
        "effective_before_bps": 0,
        "effective_after_bps": 500,
        "stored_discount_after_bps": 500,
        "after_cure_april_interest": 3_500,
        "after_cure_discount_still_off": 1,
        "after_cure_in_default": 0,
    }


def test_personal_campaign_stays_at_or_below_the_contractual_rate():
    repos = (RepoRate(date(2026, 1, 1), Decimal("0.0700")),)
    agreement = Agreement(
        product=Product.PERSONAL,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 3, 1),
        maturity_date=date(2027, 3, 1),
        margin_annual=Decimal("0.21"),
        campaign_interest_discount=Decimal("0.05"),
    )
    choice = RepoFallChoice.CONTRACT_RATE_CONTINUES
    base, stored, effective = campaign_terms(
        agreement, date(2026, 3, 1), repos, discount_active=True, repo_fall=choice
    )
    assert base == Decimal("0.28")
    assert stored == Decimal("0.05")
    assert effective == Decimal("0.23")
    assert (
        campaign_terms(agreement, date(2026, 3, 1), repos, discount_active=False, repo_fall=choice)[2]
        == base
    )
    zeroed = Agreement(
        product=Product.PERSONAL,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=date(2026, 3, 1),
        maturity_date=date(2027, 3, 1),
        margin_annual=Decimal("0.21"),
        campaign_interest_discount=Decimal("0.28"),
    )
    assert (
        campaign_terms(zeroed, date(2026, 3, 1), repos, discount_active=True, repo_fall=choice)[2]
        == Decimal("0")
    )
    state = run(
        zeroed,
        until=date(2026, 3, 1),
        policy=Policy(
            leniency_days=1,
            full_payment_threshold_percent=Decimal("100"),
            repo_fall=choice,
        ),
        repos=repos,
        vat_rates=VAT_15,
    ).state
    assert state.unbilled_ordinary == 0
    assert state.unbilled_duplum == 0


def test_rejected_configuration():
    with pytest.raises(RuleError) as leniency:
        Policy(leniency_days=-1)
    assert leniency.value.code == "leniency"
    with pytest.raises(RuleError) as threshold:
        Policy(full_payment_threshold_percent=Decimal("100.01"))
    assert threshold.value.code == "threshold"
    with pytest.raises(RuleError) as hold:
        Agreement(
            product=Product.MICRO,
            credit_provider_org_id="org",
            consumer_party_id="person",
            product_enrolment_id="enrol",
            cash_advanced_cents=100_000,
            advance_date=date(2026, 3, 1),
            maturity_date=date(2026, 9, 1),
            laybye_hold_cents=1,
        )
    assert hold.value.code == "laybye-link"
    with pytest.raises(RuleError) as discount:
        Agreement(
            product=Product.MICRO,
            credit_provider_org_id="org",
            consumer_party_id="person",
            product_enrolment_id="enrol",
            cash_advanced_cents=100_000,
            advance_date=date(2026, 3, 1),
            maturity_date=date(2026, 9, 1),
            campaign_interest_discount=Decimal("-0.01"),
        )
    assert discount.value.code == "campaign"
