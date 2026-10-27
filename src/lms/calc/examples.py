"""Worked examples. The numbers are produced by the engine, then pinned in tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from lms.calc.allocation import allocate_payment
from lms.calc.fees import initiation_cap_ex_vat_cents, initiation_fee, service_fee_cents
from lms.calc.interest import campaign_terms, interest_for_dates, micro_monthly_rate
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
    LaybyeHold,
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


def example_fresh_duplum_ceiling() -> dict[str, int]:
    """R200 in two slices. The second default's ceiling is the reduced principal.

    R150 falls due on 31 May 2026 and R50 on 31 October. The first default starts
    on 1 June with a R200 ceiling and fills it. On 15 September the consumer pays
    every due charge and the R150 slice. The next default, 1 October, is capped
    at the R50 still unpaid. The aggregate reading still blocks October.
    """
    agreement = Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org-provider",
        consumer_party_id="person-consumer",
        product_enrolment_id="enrol-micro",
        cash_advanced_cents=20_000,
        advance_date=date(2026, 5, 1),
        maturity_date=date(2026, 10, 31),
        initiation_paid_upfront=True,
        principal_instalments=(
            (date(2026, 5, 31), 15_000),
            (date(2026, 10, 31), 5_000),
        ),
    )
    fee = initiation_fee(
        20_000,
        on=date(2026, 5, 1),
        vat_rates=VAT_15,
        basis=FeeCapBasis.EXCLUSIVE,
    )[2]
    opened = (Payment(date(2026, 5, 1), fee, purpose="initiation_upfront"),)
    before = run(agreement, opened, until=date(2026, 9, 14), vat_rates=VAT_15).state
    due_charges = sum(
        charge.remaining_cents
        for charge in before.charges
        if charge.due_on <= date(2026, 9, 14)
    )
    payment = due_charges + 15_000
    cured = run(
        agreement,
        opened + (Payment(date(2026, 9, 15), payment),),
        until=date(2026, 9, 16),
        vat_rates=VAT_15,
    ).state
    fresh = run(
        agreement,
        opened + (Payment(date(2026, 9, 15), payment),),
        until=date(2026, 10, 31),
        policy=Policy(duplum_reset=DuplumReset.FRESH),
        vat_rates=VAT_15,
    ).state
    aggregate = run(
        agreement,
        opened + (Payment(date(2026, 9, 15), payment),),
        until=date(2026, 10, 31),
        policy=Policy(duplum_reset=DuplumReset.AGGREGATE),
        vat_rates=VAT_15,
    ).state
    first, second = fresh.episodes
    return {
        "episode1_ceiling": first.ceiling_cents,
        "episode1_accrued": first.accrued_cents,
        "episode1_closed_month": first.closed_on.month if first.closed_on else 0,
        "episode1_closed_day": first.closed_on.day if first.closed_on else 0,
        "principal_after_cure": cured.principal_cents,
        "cured_in_default": int(cured.in_default),
        "episode2_ceiling": second.ceiling_cents,
        "episode2_started_month": second.started_on.month,
        "episode2_started_day": second.started_on.day,
        "fresh_episode2_accrued": second.accrued_cents,
        "aggregate_episode2_accrued": aggregate.episodes[1].accrued_cents,
        "aggregate_episode2_ceiling": aggregate.episodes[1].ceiling_cents,
        "fresh_october_interest": next(
            charge.amount_cents
            for charge in fresh.charges
            if charge.kind == "interest" and charge.levied_on == date(2026, 10, 31)
        ),
        "fresh_october_service": next(
            charge.amount_cents
            for charge in fresh.charges
            if charge.kind == "service" and charge.levied_on == date(2026, 10, 31)
        ),
        "aggregate_october_interest": sum(
            charge.amount_cents
            for charge in aggregate.charges
            if charge.kind == "interest" and charge.levied_on == date(2026, 10, 31)
        ),
        "aggregate_october_service": sum(
            charge.amount_cents
            for charge in aggregate.charges
            if charge.kind == "service" and charge.levied_on == date(2026, 10, 31)
        ),
    }


def _thousand(advance: date, maturity: date, **kwargs: object) -> Agreement:
    return Agreement(
        product=Product.MICRO,
        credit_provider_org_id="org-provider",
        consumer_party_id="person-consumer",
        product_enrolment_id="enrol-micro",
        cash_advanced_cents=100_000,
        advance_date=advance,
        maturity_date=maturity,
        **kwargs,  # type: ignore[arg-type]
    )


def example_leniency_and_threshold() -> dict[str, int]:
    """R1,000 due 31 March 2026. Four days of leniency, then a 95% threshold.

    Interest for 1–3 April is R5.00 and the agreement is not in default.
    Default is flagged on 4 April if nothing was paid. A payment of exactly 95%
    of the 31 March bundle on 31 March is not a default on 4 April. One cent less is.
    """
    agreement = _thousand(
        date(2026, 3, 1),
        date(2026, 6, 30),
        initiation_paid_upfront=True,
        principal_instalments=((date(2026, 3, 31), 100_000),),
    )
    fee = initiation_fee(
        100_000,
        on=date(2026, 3, 1),
        vat_rates=VAT_15,
        basis=FeeCapBasis.EXCLUSIVE,
    )[2]
    opened = (Payment(date(2026, 3, 1), fee, purpose="initiation_upfront"),)
    grace = Policy(leniency_days=4, full_payment_threshold_percent=Decimal("100"))
    strict = Policy(leniency_days=1, full_payment_threshold_percent=Decimal("100"))
    april3 = run(agreement, opened, until=date(2026, 4, 3), policy=grace, vat_rates=VAT_15).state
    april4 = run(agreement, opened, until=date(2026, 4, 4), policy=grace, vat_rates=VAT_15).state
    end_grace = run(agreement, opened, until=date(2026, 4, 30), policy=grace, vat_rates=VAT_15).state
    end_strict = run(agreement, opened, until=date(2026, 4, 30), policy=strict, vat_rates=VAT_15).state
    march = run(agreement, opened, until=date(2026, 3, 31), policy=grace, vat_rates=VAT_15).state
    bundle = sum(charge.amount_cents for charge in march.charges if charge.due_on == date(2026, 3, 31))
    bundle += sum(slice_.amount_cents for slice_ in march.principal_slices if slice_.due_on == date(2026, 3, 31))
    pay_95 = (bundle * 95 + 99) // 100
    soft = Policy(leniency_days=4, full_payment_threshold_percent=Decimal("95"))
    cleared = run(
        agreement,
        opened + (Payment(date(2026, 3, 31), pay_95),),
        until=date(2026, 4, 4),
        policy=soft,
        vat_rates=VAT_15,
    ).state
    short = run(
        agreement,
        opened + (Payment(date(2026, 3, 31), pay_95 - 1),),
        until=date(2026, 4, 4),
        policy=soft,
        vat_rates=VAT_15,
    ).state
    from lms.calc.money import to_cents

    return {
        "april3_in_default": int(april3.in_default),
        "april3_unbilled_interest": to_cents(april3.unbilled_ordinary + april3.unbilled_duplum),
        "april4_in_default": int(april4.in_default),
        "april30_interest_leniency_4": charge_remaining(end_grace, "interest"),
        "april30_interest_leniency_1": charge_remaining(end_strict, "interest"),
        "bundle": bundle,
        "pay_95": pay_95,
        "pay_95_in_default": int(cleared.in_default),
        "pay_95_principal_left": cleared.principal_cents,
        "pay_short_in_default": int(short.in_default),
    }


def example_laybye_net_interest() -> dict[str, int]:
    """R1,000 micro loan with a R400 lay-by hold. March 2026 interest is 5% of R600.

    The loan still carries one service fee. A hold larger than principal yields
    no interest and still one service fee. The in-duplum ceiling stays the gross
    principal. Raising the hold on 16 March stops interest from that day.
    """
    from lms.calc.money import to_cents

    plain = _micro(100_000, date(2026, 3, 1), date(2026, 9, 1))
    linked = _thousand(
        date(2026, 3, 1),
        date(2026, 9, 1),
        linked_laybye_id="laybye-child",
        laybye_hold_cents=40_000,
    )
    covered = _thousand(
        date(2026, 3, 1),
        date(2026, 9, 1),
        linked_laybye_id="laybye-child",
        laybye_hold_cents=150_000,
    )
    plain_state = run(plain, until=date(2026, 3, 31), vat_rates=VAT_15).state
    linked_state = run(linked, until=date(2026, 3, 31), vat_rates=VAT_15).state
    covered_state = run(covered, until=date(2026, 3, 31), vat_rates=VAT_15).state
    stepped = run(
        linked,
        (LaybyeHold(date(2026, 3, 16), 100_000),),
        until=date(2026, 3, 31),
        vat_rates=VAT_15,
    ).state
    defaulted = run(linked, until=date(2026, 4, 1), vat_rates=VAT_15).state
    return {
        "gross_interest": charge_remaining(plain_state, "interest"),
        "net_interest": charge_remaining(linked_state, "interest"),
        "service_fee": charge_remaining(linked_state, "service"),
        "service_count": sum(1 for charge in linked_state.charges if charge.kind == "service"),
        "gross_service_fee": charge_remaining(plain_state, "service"),
        "covered_interest": charge_remaining(covered_state, "interest"),
        "covered_service_count": sum(1 for charge in covered_state.charges if charge.kind == "service"),
        "covered_service_fee": charge_remaining(covered_state, "service"),
        "duplum_ceiling": defaulted.episodes[0].ceiling_cents,
        "stepped_interest": to_cents(stepped.unbilled_ordinary + stepped.unbilled_duplum)
        + charge_remaining(stepped, "interest"),
        "stepped_service_count": sum(1 for charge in stepped.charges if charge.kind == "service"),
    }


def example_campaign_and_zeros() -> dict[str, int]:
    """Base 5% minus a 5% discount. Fees discounted to R0. Nothing divides by zero.

    The discount stays on through a 4-day leniency window and falls away on the
    flag date. It is still stored as 5% after that. A campaign that does not fall
    away stays at R0 through the missed payment.
    """
    from lms.calc.money import to_cents

    cap = initiation_cap_ex_vat_cents(100_000)
    due = ((date(2026, 3, 31), 100_000),)
    campaign = _thousand(
        date(2026, 3, 1),
        date(2026, 9, 1),
        principal_instalments=due,
        campaign_interest_discount=Decimal("0.05"),
        campaign_initiation_discount_cents=cap,
        campaign_service_discount_cents=6_000,
        campaign_falls_away_on_default=True,
    )
    sticky = _thousand(
        date(2026, 3, 1),
        date(2026, 9, 1),
        principal_instalments=due,
        campaign_interest_discount=Decimal("0.05"),
        campaign_initiation_discount_cents=cap,
        campaign_service_discount_cents=6_000,
        campaign_falls_away_on_default=False,
    )
    literal = _thousand(
        date(2026, 3, 1),
        date(2026, 9, 1),
        agreed_monthly_rate=Decimal("0"),
        campaign_initiation_discount_cents=cap,
    )
    march = run(campaign, until=date(2026, 3, 31), vat_rates=VAT_15).state
    april = run(campaign, until=date(2026, 4, 30), vat_rates=VAT_15).state
    grace = Policy(leniency_days=4)
    april3 = run(campaign, until=date(2026, 4, 3), policy=grace, vat_rates=VAT_15).state
    april30 = run(campaign, until=date(2026, 4, 30), policy=grace, vat_rates=VAT_15).state
    sticky_april = run(sticky, until=date(2026, 4, 30), vat_rates=VAT_15).state
    quote = quote_settlement(campaign, as_of=date(2026, 3, 15), vat_rates=VAT_15)
    literal_state = run(
        literal,
        until=date(2026, 4, 15),
        policy=Policy(service_fee_monthly_cents=0),
        vat_rates=VAT_15,
    ).state
    literal_quote = quote_settlement(
        literal,
        as_of=date(2026, 3, 15),
        policy=Policy(service_fee_monthly_cents=0),
        vat_rates=VAT_15,
    )
    split = _thousand(
        date(2026, 3, 1),
        date(2026, 6, 30),
        principal_instalments=((date(2026, 3, 31), 60_000), (date(2026, 6, 30), 40_000)),
        campaign_interest_discount=Decimal("0.05"),
        campaign_initiation_discount_cents=cap,
        campaign_service_discount_cents=6_000,
        campaign_falls_away_on_default=True,
    )
    # R600 of principal is paid on 15 April, after the discount has already fallen away.
    # April interest is 1–15 April on R1,000 plus 16–30 April on R400, both at the base 5%.
    cured = run(
        split,
        (Payment(date(2026, 4, 15), 60_000),),
        until=date(2026, 4, 30),
        vat_rates=VAT_15,
    ).state
    before = campaign_terms(campaign, date(2026, 3, 1), discount_active=True)
    after = campaign_terms(campaign, date(2026, 4, 1), discount_active=False)
    return {
        "march_interest": charge_remaining(march, "interest"),
        "march_service": charge_remaining(march, "service"),
        "march_initiation": charge_remaining(march, "initiation"),
        "april_interest": charge_remaining(april, "interest"),
        "april_service": charge_remaining(april, "service"),
        "april_in_default": int(april.in_default),
        "leniency_april3_in_default": int(april3.in_default),
        "leniency_april3_unbilled": to_cents(april3.unbilled_ordinary + april3.unbilled_duplum),
        "leniency_april_interest": charge_remaining(april30, "interest"),
        "sticky_april_interest": charge_remaining(sticky_april, "interest"),
        "sticky_april_in_default": int(sticky_april.in_default),
        "quote_total": quote.total_cents,
        "literal_interest": charge_remaining(literal_state, "interest"),
        "literal_service": charge_remaining(literal_state, "service"),
        "literal_initiation": charge_remaining(literal_state, "initiation"),
        "literal_quote": literal_quote.total_cents,
        "base_bps": int(before[0] * 10_000),
        "discount_bps": int(before[1] * 10_000),
        "effective_before_bps": int(before[2] * 10_000),
        "effective_after_bps": int(after[2] * 10_000),
        "stored_discount_after_bps": int(after[1] * 10_000),
        "after_cure_april_interest": charge_remaining(cured, "interest"),
        "after_cure_discount_still_off": int(not cured.campaign_discount_active),
        "after_cure_in_default": int(cured.in_default),
    }


EXAMPLES = {
    "initiation": example_initiation_caps,
    "partial_month": example_partial_month_interest,
    "first_subsequent": example_first_versus_subsequent,
    "repo": example_repo_step,
    "service_vat": example_service_fee_and_vat,
    "partial_payment": example_partial_payment,
    "duplum": example_duplum,
    "fresh_ceiling": example_fresh_duplum_ceiling,
    "leniency": example_leniency_and_threshold,
    "laybye_net": example_laybye_net_interest,
    "campaign": example_campaign_and_zeros,
    "settlement": example_settlement,
    "laybye": example_laybye,
}
