"""Pinned day-1 figures. If a formula changes, these tests must be updated with the rules document."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from lms.calc.examples import (
    VAT_15,
    example_duplum,
    example_first_versus_subsequent,
    example_initiation_caps,
    example_laybye,
    example_partial_month_interest,
    example_partial_payment,
    example_repo_step,
    example_service_fee_and_vat,
    example_settlement,
)
from lms.calc.interest import interest_for_dates
from lms.calc.laybye import guard_s124
from lms.calc.ledger import charge_remaining, run
from lms.calc.models import (
    Agreement,
    FeeCapBasis,
    Payment,
    Policy,
    PrepaymentChoice,
    Product,
    RepoFallChoice,
    RepoRate,
    agreement_size,
)

# The engine fails closed. These tests state the customer's choice.
STATED = dict(leniency_days=1, full_payment_threshold_percent=Decimal("100"))
from lms.calc.money import RuleError, to_cents
from lms.calc.examples import _micro, _personal


def test_initiation_caps():
    assert example_initiation_caps() == {
        "r800": 12_000,
        "r1000": 15_000,
        "r1300": 19_500,
        "r1301": 19_510,
        "r4000": 46_500,
        "r9850": 105_000,
        "r10000": 105_000,
        "r150": 2_250,
        "r800_vat": 1_800,
        "r800_total": 13_800,
        "r800_inclusive_total": 12_000,
    }


def test_partial_month_interest():
    assert example_partial_month_interest() == {
        "partial_actual": 3_871,
        "partial_fixed_30": 4_000,
        "full_january_actual": 10_000,
        "full_january_fixed_30": 10_333,
    }


def test_first_versus_subsequent_rate():
    assert example_first_versus_subsequent() == {
        "first_interest": 5_000,
        "subsequent_interest": 3_000,
        "same_day_subsequent_bps": 300,
        "new_year_first_bps": 500,
    }


def test_repo_step():
    assert example_repo_step() == {
        "rise_continues": 8_438,
        "rise_lower": 8_438,
        "fall_continues": 8_514,
        "fall_lower": 8_473,
        "leap_day_actual": 772,
        "leap_day_fixed_365": 774,
    }


def test_service_fee_prorata_and_hypothetical_vat():
    assert example_service_fee_and_vat() == {
        "march_service_ex_vat": 6_000,
        "march_service_vat": 900,
        "march_service_total": 6_900,
        "april_full_ex_vat": 6_000,
        "april_full_vat": 960,
        "april_full_total": 6_960,
        "april_prorata_total": 2_320,
        "quote_full_interest": 17_635,
        "quote_full_fees": 67_335,
        "quote_full_principal": 400_000,
        "quote_full_total": 484_970,
        "quote_prorata_total": 480_330,
        "early_termination": 0,
        "valid_until_day": 17,
    }


def test_partial_payment_allocation():
    assert example_partial_payment() == {
        "interest_after_200": 0,
        "initiation_after_200": 9_150,
        "service_after_200": 0,
        "principal_after_200": 100_000,
        "interest_after_300": 0,
        "initiation_after_300": 0,
        "service_after_300": 0,
        "principal_after_300": 99_150,
    }


def test_duplum_freeze_release_and_reset_choice():
    assert example_duplum() == {
        "july_episode_accrued": 15_000,
        "july_ceiling": 15_000,
        "august_interest_remaining": 1_250,
        "august_episode_accrued": 15_000,
        "august_still_open": 1,
        "purge_payment": 22_650,
        "september_interest": 375,
        "september_in_default": 0,
        "october_fresh_interest": 1_125,
        "october_fresh_service": 13_800,
        "october_fresh_episode2": 7_650,
        "october_aggregate_interest": 375,
        "october_aggregate_service": 6_900,
        "october_aggregate_episode2": 0,
        "pre_default_initiation": 2_588,
        "initiation_unpaid_after_purge": 2_588,
        "july_service_charged": 6_600,
    }


def test_settlement_quote_window_and_short_payment():
    assert example_settlement() == {
        "quote_total": 484_910,
        "quote_interest": 17_635,
        "quote_fees": 67_275,
        "quote_principal": 400_000,
        "early_termination": 0,
        "valid_until_day": 17,
        "holiday_valid_until_day": 30,
        "plain_valid_until_day": 29,
        "paid_status_settled": 1,
        "waived": 4_666,
        "short_status_open": 1,
        "short_principal": 0,
        "short_service_remaining": 1,
        "late_status_open": 1,
        "late_principal": 0,
        "late_service_remaining": 5_333,
    }


def test_laybye_penalty_and_security_application():
    assert example_laybye() == {
        "penalty": 2_000,
        "refund": 78_000,
        "silent_refund": 80_000,
        "hospital_refund": 80_000,
        "arrears": 29_150,
        "applied": 29_150,
        "hold_remaining": 850,
        "interest_left": 0,
        "fees_left": 0,
        "principal_left": 100_000,
        "default_next_day": 0,
    }


def test_full_periods_land_on_the_stated_rate():
    micro = _micro(200_000, date(2026, 1, 1), date(2026, 7, 1))
    state = run(micro, until=date(2026, 6, 30), policy=Policy(**STATED), vat_rates=VAT_15).state
    assert charge_remaining(state, "interest") == 60_000  # 6 × 5% × R2,000

    personal = _personal(1_000_000, date(2026, 1, 1), date(2027, 1, 1))
    exact = interest_for_dates(
        base_cents=1_000_000,
        agreement=personal,
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
        repos=(RepoRate(date(2026, 1, 1), Decimal("0.0725")),),
        repo_fall=RepoFallChoice.CONTRACT_RATE_CONTINUES,
    )
    assert to_cents(exact) == to_cents(Decimal(10_000) * Decimal("0.2825"))


def test_deferred_initiation_does_not_start_default_and_does_not_bear_interest():
    agreement = _micro(100_000, date(2026, 3, 1), date(2026, 9, 1))
    state = run(agreement, until=date(2026, 3, 2), policy=Policy(**STATED), vat_rates=VAT_15).state
    assert state.in_default is False
    assert charge_remaining(state, "interest") == 0  # not billed until month-end

    month = run(agreement, until=date(2026, 3, 31), policy=Policy(**STATED), vat_rates=VAT_15).state
    with_fee = run(
        agreement,
        until=date(2026, 3, 31),
        policy=Policy(interest_on_deferred_initiation=True, **STATED),
        vat_rates=VAT_15,
    ).state
    assert charge_remaining(month, "interest") == 5_000
    assert charge_remaining(with_fee, "interest") == 5_835


def test_upfront_initiation_payment_clears_the_fee():
    advance = date(2026, 3, 1)
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org-provider",
        consumer_party_id="person-consumer",
        product_enrolment_id="enrol-micro",
        cash_advanced_cents=100_000,
        advance_date=advance,
        maturity_date=date(2026, 9, 1),
        initiation_paid_upfront=True,
    )
    from lms.calc.fees import initiation_fee
    from lms.calc.models import FeeCapBasis, Payment

    total = initiation_fee(
        100_000, on=advance, vat_rates=VAT_15, basis=FeeCapBasis.EXCLUSIVE
    )[2]
    unpaid = run(
        agreement, until=advance + timedelta(days=1), policy=Policy(**STATED), vat_rates=VAT_15
    ).state
    assert unpaid.in_default is True
    paid = run(
        agreement,
        (Payment(advance, total, purpose="initiation_upfront"),),
        until=advance + timedelta(days=1),
        policy=Policy(**STATED),
        vat_rates=VAT_15,
    ).state
    assert charge_remaining(paid, "initiation") == 0
    assert paid.in_default is False


def test_agreement_size_and_product_guards():
    assert agreement_size(1_500_000) == "small"
    assert agreement_size(1_500_001) == "intermediate"
    assert agreement_size(25_000_000) == "large"
    with pytest.raises(RuleError) as too_big:
        _micro(800_001, date(2026, 1, 1), date(2026, 6, 1))
    assert too_big.value.code == "short-term-amount"
    with pytest.raises(RuleError) as too_long:
        _micro(100_000, date(2026, 5, 1), date(2026, 11, 2))
    assert too_long.value.code == "short-term-term"
    with pytest.raises(RuleError) as margin:
        Agreement(
            product=Product.PERSONAL,
            credit_provider_org_id="org",
            consumer_party_id="person",
            product_enrolment_id="enrol",
            cash_advanced_cents=1_000_000,
            advance_date=date(2026, 1, 1),
            maturity_date=date(2027, 1, 1),
            margin_annual=Decimal("0.22"),
        )
    assert margin.value.code == "unsecured-margin"
    with pytest.raises(RuleError) as large:
        _personal(25_000_000, date(2026, 1, 1), date(2028, 1, 1))
    assert large.value.code == "day1-large"


def test_principal_prepayment_reduces_the_earliest_slice():
    from lms.calc.fees import initiation_fee

    advance = date(2026, 3, 1)
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org",
        consumer_party_id="person",
        product_enrolment_id="enrol",
        cash_advanced_cents=100_000,
        advance_date=advance,
        maturity_date=date(2026, 5, 1),
        principal_instalments=((date(2026, 4, 1), 40_000), (date(2026, 5, 1), 60_000)),
        initiation_paid_upfront=True,
    )
    fee = initiation_fee(100_000, on=advance, vat_rates=VAT_15, basis=FeeCapBasis.EXCLUSIVE)[2]
    preview = run(
        agreement,
        (Payment(advance, fee, purpose="initiation_upfront"),),
        until=date(2026, 3, 31),
        policy=Policy(**STATED),
        vat_rates=VAT_15,
    ).state
    due_cost = sum(charge.remaining_cents for charge in preview.charges)
    state = run(
        agreement,
        (
            Payment(advance, fee, purpose="initiation_upfront"),
            Payment(date(2026, 3, 31), due_cost + 1_000),
        ),
        until=date(2026, 3, 31),
        policy=Policy(prepayment_choice=PrepaymentChoice.DROP_INSTALMENT, **STATED),
        vat_rates=VAT_15,
    ).state
    assert [(slice_.due_on, slice_.remaining_cents) for slice_ in state.principal_slices] == [
        (date(2026, 4, 1), 39_000),
        (date(2026, 5, 1), 60_000),
    ]


def test_security_application_requires_a_mandate():
    with pytest.raises(RuleError) as missing:
        guard_s124(
            mandate_id="",
            authorised_cents=1_000,
            requested_cents=1_000,
            on=date(2026, 3, 31),
            authorised_from=date(2026, 3, 1),
            authorised_to=None,
        )
    assert missing.value.code == "s124-mandate-missing"
