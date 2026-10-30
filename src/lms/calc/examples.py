"""Worked examples. The numbers are produced by the engine, then pinned in tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from lms.calc.allocation import allocate_payment
from lms.calc.fees import initiation_cap_ex_vat_cents, initiation_fee, service_fee_cents
from lms.calc.interest import interest_for_dates, micro_monthly_rate
from lms.calc.laybye import cancel_laybye, guard_s124
from lms.calc.ledger import (
    DEFAULT_VAT,
    charge_remaining,
    episode_accrued,
    execute_settlement,
    quote_settlement,
    run,
)
from lms.calc.models import (
    Agreement,
    DayCount,
    DuplumReset,
    FeeCapBasis,
    Payment,
    Policy,
    Product,
    RepoRate,
    TerminalServiceFee,
    VatRate,
)

# SARB raised the policy rate by 25bp to 7.25% effective 25 September 2026.
# 7.00% is the rate that increase moved from. It is an input, not a live fetch.
REPOS: tuple[RepoRate, ...] = (
    RepoRate(date(2026, 1, 1), Decimal("0.0700")),
    RepoRate(date(2026, 9, 25), Decimal("0.0725")),
)

# The May 2025 VAT increase was reversed. 15% remains the standard rate.
# The 16% row below is a hypothetical schedule used only to show a mid-loan change.
VAT_15: tuple[VatRate, ...] = DEFAULT_VAT
VAT_HYPOTHETICAL: tuple[VatRate, ...] = (
    VatRate(date(2018, 4, 1), Decimal("0.15")),
    VatRate(date(2026, 4, 1), Decimal("0.16")),
)


def _micro(
    cash_cents: int,
    advance: date,
    maturity: date,
    priors: tuple[date, ...] = (),
) -> Agreement:
    return Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org-provider",
        consumer_party_id="person-consumer",
        product_enrolment_id="enrol-micro",
        cash_advanced_cents=cash_cents,
        advance_date=advance,
        maturity_date=maturity,
        prior_short_term_inceptions=priors,
    )


def _personal(cash_cents: int, advance: date, maturity: date) -> Agreement:
    return Agreement(
        product=Product.PERSONAL,
        credit_provider_org_id="org-provider",
        consumer_party_id="person-consumer",
        product_enrolment_id="enrol-personal",
        cash_advanced_cents=cash_cents,
        advance_date=advance,
        maturity_date=maturity,
        margin_annual=Decimal("0.21"),
    )


def example_initiation_caps() -> dict[str, int]:
    """Cash advanced → prescribed initiation cap in ex-VAT cents."""
    principals = {
        "r800": 80_000,
        "r1000": 100_000,
        "r1300": 130_000,
        "r1301": 130_100,
        "r4000": 400_000,
        "r9850": 985_000,
        "r10000": 1_000_000,
        "r150": 15_000,
    }
    caps = {name: initiation_cap_ex_vat_cents(cents) for name, cents in principals.items()}
    priced = initiation_fee(80_000, on=date(2026, 3, 1), vat_rates=VAT_15, basis=FeeCapBasis.EXCLUSIVE)
    inclusive = initiation_fee(80_000, on=date(2026, 3, 1), vat_rates=VAT_15, basis=FeeCapBasis.INCLUSIVE)
    caps["r800_vat"] = priced[1]
    caps["r800_total"] = priced[2]
    caps["r800_inclusive_total"] = inclusive[2]
    return caps


def example_partial_month_interest() -> dict[str, int]:
    """R2,000 at 5% from 20 January 2026 through 31 January, actual days and the 30-day alternative."""
    agreement = _micro(200_000, date(2026, 1, 20), date(2026, 7, 20))
    actual = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 20),
        end=date(2026, 1, 31),
        day_count=DayCount.ACTUAL,
    )
    fixed = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 20),
        end=date(2026, 1, 31),
        day_count=DayCount.FIXED,
    )
    full_actual = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        day_count=DayCount.ACTUAL,
    )
    full_fixed = interest_for_dates(
        base_cents=200_000,
        agreement=agreement,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        day_count=DayCount.FIXED,
    )
    from lms.calc.money import to_cents

    return {
        "partial_actual": to_cents(actual),
        "partial_fixed_30": to_cents(fixed),
        "full_january_actual": to_cents(full_actual),
        "full_january_fixed_30": to_cents(full_fixed),
    }


def example_first_versus_subsequent() -> dict[str, int]:
    """R1,000 for the whole of February 2026. First loan 5%, second loan 3%."""
    from lms.calc.money import to_cents

    first = _micro(100_000, date(2026, 2, 1), date(2026, 8, 1))
    second = _micro(
        100_000,
        date(2026, 2, 1),
        date(2026, 8, 1),
        priors=(date(2026, 1, 15),),
    )
    same_day = micro_monthly_rate(date(2026, 2, 1), (date(2026, 2, 1),))
    new_year = micro_monthly_rate(date(2027, 1, 1), (date(2026, 12, 1),))
    return {
        "first_interest": to_cents(
            interest_for_dates(
                base_cents=100_000,
                agreement=first,
                start=date(2026, 2, 1),
                end=date(2026, 2, 28),
            )
        ),
        "subsequent_interest": to_cents(
            interest_for_dates(
                base_cents=100_000,
                agreement=second,
                start=date(2026, 2, 1),
                end=date(2026, 2, 28),
            )
        ),
        "same_day_subsequent_bps": int(same_day * 10_000),
        "new_year_first_bps": int(new_year * 10_000),
    }


def example_repo_step() -> dict[str, int]:
    """R10,000 unsecured, RR+21%, 20-30 September 2026, actual/365."""
    from lms.calc.money import to_cents

    agreement = _personal(1_000_000, date(2026, 9, 20), date(2027, 9, 20))
    total = interest_for_dates(
        base_cents=1_000_000,
        agreement=agreement,
        start=date(2026, 9, 20),
        end=date(2026, 9, 30),
        repos=REPOS,
    )
    before = interest_for_dates(
        base_cents=1_000_000,
        agreement=agreement,
        start=date(2026, 9, 20),
        end=date(2026, 9, 24),
        repos=REPOS,
    )
    after = interest_for_dates(
        base_cents=1_000_000,
        agreement=agreement,
        start=date(2026, 9, 25),
        end=date(2026, 9, 30),
        repos=REPOS,
    )
    leap_actual = interest_for_dates(
        base_cents=1_000_000,
        agreement=_personal(1_000_000, date(2028, 2, 29), date(2028, 8, 29)),
        start=date(2028, 2, 29),
        end=date(2028, 2, 29),
        repos=(RepoRate(date(2028, 1, 1), Decimal("0.0725")),),
        day_count=DayCount.ACTUAL,
    )
    leap_fixed = interest_for_dates(
        base_cents=1_000_000,
        agreement=_personal(1_000_000, date(2028, 2, 29), date(2028, 8, 29)),
        start=date(2028, 2, 29),
        end=date(2028, 2, 29),
        repos=(RepoRate(date(2028, 1, 1), Decimal("0.0725")),),
        day_count=DayCount.FIXED,
    )
    return {
        "before_hike": to_cents(before),
        "after_hike": to_cents(after),
        "total": to_cents(total),
        "leap_day_actual": to_cents(leap_actual),
        "leap_day_fixed_365": to_cents(leap_fixed),
    }


def example_service_fee_and_vat() -> dict[str, int]:
    """Conclude 15 March 2026, settle 10 April. Hypothetical VAT 16% from 1 April."""
    agreement = _micro(400_000, date(2026, 3, 15), date(2026, 9, 15))
    full = quote_settlement(
        agreement,
        as_of=date(2026, 4, 10),
        delivered_on=date(2026, 4, 10),
        vat_rates=VAT_HYPOTHETICAL,
        policy=Policy(terminal_service_fee=TerminalServiceFee.FULL),
    )
    pro_rata = quote_settlement(
        agreement,
        as_of=date(2026, 4, 10),
        delivered_on=date(2026, 4, 10),
        vat_rates=VAT_HYPOTHETICAL,
        policy=Policy(terminal_service_fee=TerminalServiceFee.PRO_RATA),
    )
    march_fee = service_fee_cents(
        on=date(2026, 3, 31),
        period_start=date(2026, 3, 15),
        period_end=date(2026, 3, 31),
        vat_rates=VAT_HYPOTHETICAL,
        basis=FeeCapBasis.EXCLUSIVE,
    )
    april_full = service_fee_cents(
        on=date(2026, 4, 10),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        full_month=True,
        vat_rates=VAT_HYPOTHETICAL,
        basis=FeeCapBasis.EXCLUSIVE,
    )
    april_pro_rata = service_fee_cents(
        on=date(2026, 4, 10),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 10),
        vat_rates=VAT_HYPOTHETICAL,
        basis=FeeCapBasis.EXCLUSIVE,
    )
    return {
        "march_service_ex_vat": march_fee[0],
        "march_service_vat": march_fee[1],
        "march_service_total": march_fee[2],
        "april_full_ex_vat": april_full[0],
        "april_full_vat": april_full[1],
        "april_full_total": april_full[2],
        "april_prorata_total": april_pro_rata[2],
        "quote_full_interest": full.interest_cents,
        "quote_full_fees": full.fee_cents,
        "quote_full_principal": full.principal_cents,
        "quote_full_total": full.total_cents,
        "quote_prorata_total": pro_rata.total_cents,
        "early_termination": full.early_termination_cents,
        "valid_until_day": full.valid_until.day,
    }


def example_partial_payment() -> dict[str, int]:
    """R1,000 advanced 1 March 2026. R200 at month-end, then a further R100 on that balance.

    The second payment is allocated on the month-end balance. It is not folded
    into 1 April, because 1 April would already be a default day.
    """
    agreement = _micro(100_000, date(2026, 3, 1), date(2026, 9, 1))
    march = run(
        agreement,
        (Payment(date(2026, 3, 31), 20_000),),
        until=date(2026, 3, 31),
    ).state
    second = allocate_payment(march, 10_000).state
    return {
        "interest_after_200": charge_remaining(march, "interest"),
        "initiation_after_200": charge_remaining(march, "initiation"),
        "service_after_200": charge_remaining(march, "service"),
        "principal_after_200": march.principal_cents,
        "interest_after_300": charge_remaining(second, "interest"),
        "initiation_after_300": charge_remaining(second, "initiation"),
        "service_after_300": charge_remaining(second, "service"),
        "principal_after_300": second.principal_cents,
    }


def example_duplum() -> dict[str, int]:
    """R150 bullet loan advanced 1 May 2026. Cap reached in July. Payment does not restart it."""
    agreement = _micro(15_000, date(2026, 5, 1), date(2026, 10, 31))
    frozen = run(
        agreement,
        (Payment(date(2026, 8, 15), 1_000),),
        until=date(2026, 8, 16),
    ).state
    end_july = run(agreement, until=date(2026, 7, 31)).state
    arrears_before_purge = run(agreement, until=date(2026, 9, 14)).state
    due = sum(
        charge.remaining_cents
        for charge in arrears_before_purge.charges
        if charge.due_on <= date(2026, 9, 14)
    )
    purged = run(
        agreement,
        (Payment(date(2026, 9, 15), due),),
        until=date(2026, 9, 30),
    ).state
    october_fresh = run(
        agreement,
        (Payment(date(2026, 9, 15), due),),
        until=date(2026, 10, 31),
        policy=Policy(duplum_reset=DuplumReset.FRESH),
    ).state
    october_aggregate = run(
        agreement,
        (Payment(date(2026, 9, 15), due),),
        until=date(2026, 10, 31),
        policy=Policy(duplum_reset=DuplumReset.AGGREGATE),
    ).state
    return {
        "july_episode_accrued": episode_accrued(end_july, 1),
        "july_ceiling": end_july.episodes[0].ceiling_cents,
        "august_interest_remaining": charge_remaining(frozen, "interest"),
        "august_episode_accrued": episode_accrued(frozen, 1),
        "august_still_open": int(frozen.episodes[0].closed_on is None),
        "purge_payment": due,
        "september_interest": charge_remaining(purged, "interest"),
        "september_in_default": int(purged.in_default),
        "october_fresh_interest": charge_remaining(october_fresh, "interest"),
        "october_fresh_service": charge_remaining(october_fresh, "service"),
        "october_fresh_episode2": episode_accrued(october_fresh, 2),
        "october_aggregate_interest": charge_remaining(october_aggregate, "interest"),
        "october_aggregate_service": charge_remaining(october_aggregate, "service"),
        "october_aggregate_episode2": episode_accrued(october_aggregate, 2),
        "pre_default_initiation": next(
            charge.amount_cents
            for charge in end_july.charges
            if charge.kind == "initiation"
        ),
        "initiation_unpaid_after_purge": charge_remaining(purged, "initiation"),
        "july_service_charged": next(
            charge.amount_cents
            for charge in end_july.charges
            if charge.kind == "service" and charge.levied_on == date(2026, 7, 31)
        ),
    }


def example_settlement() -> dict[str, int]:
    """R4,000 advanced 15 March 2026, quoted 10 April, paid inside and outside the window."""
    from datetime import date as date_cls

    agreement = _micro(400_000, date(2026, 3, 15), date(2026, 9, 15))
    # One public holiday inside a later window, to show the five-business-day count.
    freedom_day = date_cls(2026, 4, 27)
    quote = quote_settlement(
        agreement,
        as_of=date(2026, 4, 10),
        delivered_on=date(2026, 4, 10),
        vat_rates=VAT_15,
    )
    holiday_quote = quote_settlement(
        agreement,
        as_of=date(2026, 4, 22),
        delivered_on=date(2026, 4, 22),
        vat_rates=VAT_15,
        holidays=frozenset({freedom_day}),
    )
    plain_quote = quote_settlement(
        agreement,
        as_of=date(2026, 4, 22),
        delivered_on=date(2026, 4, 22),
        vat_rates=VAT_15,
    )
    paid = execute_settlement(
        agreement,
        quote,
        quote.total_cents,
        date(2026, 4, 17),
        vat_rates=VAT_15,
    )
    short = execute_settlement(
        agreement,
        quote,
        quote.total_cents - 1,
        date(2026, 4, 10),
        vat_rates=VAT_15,
    )
    late = execute_settlement(
        agreement,
        quote,
        quote.total_cents,
        date(2026, 4, 18),
        vat_rates=VAT_15,
    )
    return {
        "quote_total": quote.total_cents,
        "quote_interest": quote.interest_cents,
        "quote_fees": quote.fee_cents,
        "quote_principal": quote.principal_cents,
        "early_termination": quote.early_termination_cents,
        "valid_until_day": quote.valid_until.day,
        "holiday_valid_until_day": holiday_quote.valid_until.day,
        "plain_valid_until_day": plain_quote.valid_until.day,
        "paid_status_settled": int(paid.state.status == "settled"),
        "waived": paid.state.waived_cents,
        "short_status_open": int(short.state.status == "open"),
        "short_principal": short.state.principal_cents,
        "short_service_remaining": charge_remaining(short.state, "service"),
        "late_status_open": int(late.state.status == "open"),
        "late_principal": late.state.principal_cents,
        "late_service_remaining": charge_remaining(late.state, "service"),
    }


def example_laybye() -> dict[str, int]:
    """CPA cancellation, and a s 126 application of a security hold to arrears."""
    disclosed = cancel_laybye(
        purchase_price_cents=200_000,
        paid_cents=80_000,
        penalty_disclosed=True,
        cause="consumer",
    )
    silent = cancel_laybye(
        purchase_price_cents=200_000,
        paid_cents=80_000,
        penalty_disclosed=False,
        cause="consumer",
    )
    hospital = cancel_laybye(
        purchase_price_cents=200_000,
        paid_cents=80_000,
        penalty_disclosed=True,
        cause="hospitalisation",
    )
    # Reuse the March partial-payment loan: after month-end the arrears are interest + fees.
    agreement = _micro(100_000, date(2026, 3, 1), date(2026, 9, 1))
    before = run(agreement, until=date(2026, 3, 31)).state
    arrears = sum(charge.remaining_cents for charge in before.charges)
    held = 30_000
    applied = min(held, arrears)
    authorised = guard_s124(
        mandate_id="mandate-s124",
        authorised_cents=arrears,
        requested_cents=applied,
        on=date(2026, 3, 31),
        authorised_from=date(2026, 3, 1),
        authorised_to=date(2026, 9, 1),
    )
    after = run(
        agreement,
        (Payment(date(2026, 3, 31), authorised, source="laybye_security"),),
        until=date(2026, 3, 31),
    ).state
    return {
        "penalty": disclosed.penalty_cents,
        "refund": disclosed.refund_cents,
        "silent_refund": silent.refund_cents,
        "hospital_refund": hospital.refund_cents,
        "arrears": arrears,
        "applied": authorised,
        "hold_remaining": held - authorised,
        "interest_left": charge_remaining(after, "interest"),
        "fees_left": charge_remaining(after, "initiation") + charge_remaining(after, "service"),
        "principal_left": after.principal_cents,
        "default_next_day": int(
            run(
                agreement,
                (Payment(date(2026, 3, 31), authorised, source="laybye_security"),),
                until=date(2026, 4, 1),
            ).state.in_default
        ),
    }


EXAMPLES = {
    "initiation": example_initiation_caps,
    "partial_month": example_partial_month_interest,
    "first_subsequent": example_first_versus_subsequent,
    "repo": example_repo_step,
    "service_vat": example_service_fee_and_vat,
    "partial_payment": example_partial_payment,
    "duplum": example_duplum,
    "settlement": example_settlement,
    "laybye": example_laybye,
}
