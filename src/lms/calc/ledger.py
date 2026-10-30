"""Fold civil days into a loan state. Every public function is pure."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from lms.calc.allocation import allocate_payment
from lms.calc.calendar import binding_until, month_end
from lms.calc.fees import (
    apply_ex_vat_discount,
    initiation_fee,
    opening_service_fraction,
    service_fee_cents,
    vat_on,
)
from lms.calc.interest import accrual_weight, campaign_terms, daily_interest_rands, divisor_days
from lms.calc.models import (
    Agreement,
    Charge,
    Clip,
    DuplumEpisode,
    DuplumReset,
    Event,
    LaybyeHold,
    ManualCharge,
    Payment,
    Policy,
    PrincipalSlice,
    Product,
    RepoRate,
    Settlement,
    State,
    TerminalServiceFee,
    VatRate,
    agreement_size,
)
from lms.calc.money import RuleError, add_vat, cents_to_rands, split_inclusive, to_cents

DEFAULT_VAT: tuple[VatRate, ...] = (VatRate(date(2018, 4, 1), Decimal("0.15")),)


@dataclass(frozen=True)
class SettlementQuote:
    as_of: date
    delivered_on: date
    valid_until: date
    principal_cents: int
    interest_cents: int
    fee_cents: int
    early_termination_cents: int
    total_cents: int
    agreement_size: str
    components: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RunResult:
    state: State
    quote: SettlementQuote | None = None


def payoff_cents(state: State) -> int:
    unbilled = to_cents(state.unbilled_ordinary + state.unbilled_duplum)
    return (
        state.principal_cents
        + sum(charge.remaining_cents for charge in state.charges)
        + unbilled
    )


def _initial(agreement: Agreement) -> State:
    slices = tuple(
        PrincipalSlice(due_on, amount, amount, index)
        for index, (due_on, amount) in enumerate(agreement.resolved_instalments())
    )
    return State(
        as_of=None,
        status="open",
        principal_slices=slices,
        charges=(),
        unbilled_ordinary=Decimal("0"),
        unbilled_duplum=Decimal("0"),
        unbilled_duplum_episode=None,
        duplum_interest_counted_cents=0,
        episodes=(),
        in_default=False,
        next_sequence=1,
        next_episode_no=1,
        prior_duplum_accrued_cents=0,
        service_months_levied=(),
        initiation_levied=False,
        suspense_cents=0,
        clips=(),
        waived_cents=0,
        settled_on=None,
        laybye_hold_cents=agreement.laybye_hold_cents,
        campaign_discount_active=True,
    )


def _open_episode(state: State) -> DuplumEpisode | None:
    for episode in state.episodes:
        if episode.closed_on is None:
            return episode
    return None


def _replace_episode(state: State, updated: DuplumEpisode) -> tuple[DuplumEpisode, ...]:
    return tuple(
        updated if episode.episode_no == updated.episode_no else episode
        for episode in state.episodes
    )


def _due_bundles(state: State) -> dict[date, tuple[int, int]]:
    """Original and remaining cents of everything that shares a contractual due date.

    Unbilled interest is not in a bundle. It is not payable until it is debited.
    """
    original: dict[date, int] = {}
    remaining: dict[date, int] = {}
    for slice_ in state.principal_slices:
        original[slice_.due_on] = original.get(slice_.due_on, 0) + slice_.amount_cents
        remaining[slice_.due_on] = remaining.get(slice_.due_on, 0) + slice_.remaining_cents
    for charge in state.charges:
        original[charge.due_on] = original.get(charge.due_on, 0) + charge.amount_cents
        remaining[charge.due_on] = remaining.get(charge.due_on, 0) + charge.remaining_cents
    return {due_on: (original[due_on], remaining[due_on]) for due_on in original}


def _below_threshold(original: int, remaining: int, threshold_percent: Decimal) -> bool:
    if original <= 0:
        return False
    received = original - remaining
    return Decimal(received) * Decimal(100) < Decimal(original) * threshold_percent


def _require_default_config(policy: Policy) -> None:
    """§6: unset leniency or threshold fails closed. Do not assume 1 day or 100%."""
    if policy.leniency_days is None:
        raise RuleError(
            "leniency-unset",
            "leniency_days is unset. LOCKED_DECISIONS §6 fails closed.",
        )
    if policy.full_payment_threshold_percent is None:
        raise RuleError(
            "threshold-unset",
            "full_payment_threshold_percent is unset. LOCKED_DECISIONS §6 fails closed.",
        )


def _overdue(state: State, day: date, policy: Policy) -> bool:
    """True when a contractual due date plus leniency has arrived and the bundle is short.

    Flag date = due date + leniency_days. Leniency counts calendar days, including
    weekends and public holidays (§6). The caller must already have applied any
    receipt recognised at 00:00 on this day.
    """
    _require_default_config(policy)
    assert policy.leniency_days is not None
    assert policy.full_payment_threshold_percent is not None
    for due_on, (original, remaining) in _due_bundles(state).items():
        if day < due_on + timedelta(days=policy.leniency_days):
            continue
        if _below_threshold(original, remaining, policy.full_payment_threshold_percent):
            return True
    return False


def _cured(state: State, day: date, policy: Policy) -> bool:
    return not _overdue(state, day, policy)


def _interest_base_cents(state: State, policy: Policy) -> int:
    # LOCKED_DECISIONS §4: interest on principal minus the linked lay-by hold.
    # The hold does not reduce the in-duplum ceiling. A hold above principal
    # yields a zero base. It does not create a credit balance.
    base = max(0, state.principal_cents - state.laybye_hold_cents)
    if policy.interest_on_deferred_initiation:
        base += sum(
            charge.remaining_cents for charge in state.charges if charge.kind == "initiation"
        )
    return base


def _prior_cents(state: State, policy: Policy) -> int:
    if policy.duplum_reset == DuplumReset.AGGREGATE:
        return state.prior_duplum_accrued_cents
    return 0


def _room_cents(state: State, policy: Policy, *, include_unbilled: bool) -> int:
    episode = _open_episode(state)
    if episode is None:
        return 0
    used = episode.accrued_cents + _prior_cents(state, policy)
    if include_unbilled:
        used += to_cents(state.unbilled_duplum)
    return max(0, episode.ceiling_cents - used)


def _room_rands(state: State, policy: Policy) -> Decimal:
    episode = _open_episode(state)
    if episode is None or not state.in_default:
        return Decimal("Infinity")
    used = (
        cents_to_rands(episode.accrued_cents + _prior_cents(state, policy))
        + state.unbilled_duplum
    )
    return max(Decimal(0), cents_to_rands(episode.ceiling_cents) - used)


def _add_charge(
    state: State,
    *,
    kind: str,
    on: date,
    ex_vat_cents: int,
    vat_cents: int,
    total_cents: int,
    episode_no: int | None,
    due_on: date | None = None,
) -> State:
    if total_cents <= 0:
        return state
    charge = Charge(
        charge_id=f"{kind}-{state.next_sequence}",
        kind=kind,
        levied_on=on,
        due_on=due_on or on,
        ex_vat_cents=ex_vat_cents,
        vat_cents=vat_cents,
        amount_cents=total_cents,
        remaining_cents=total_cents,
        duplum_episode=episode_no,
        sequence=state.next_sequence,
    )
    return replace(state, charges=state.charges + (charge,), next_sequence=state.next_sequence + 1)


def _open_default(state: State, day: date, agreement: Agreement) -> State:
    """Open a fresh episode. The ceiling is unpaid principal at this default (§7).

    A capitalised initiation fee added before this day is already inside
    ``principal_cents``, so it sits inside the ceiling. The hold does not
    reduce the ceiling (§4).
    """
    discount_active = state.campaign_discount_active
    if agreement.campaign_falls_away_on_default:
        discount_active = False
    if _open_episode(state) is not None:
        return replace(state, in_default=True, campaign_discount_active=discount_active)
    episode = DuplumEpisode(
        episode_no=state.next_episode_no,
        started_on=day,
        ceiling_cents=state.principal_cents,
        accrued_cents=0,
        closed_on=None,
    )
    return replace(
        state,
        in_default=True,
        episodes=state.episodes + (episode,),
        next_episode_no=state.next_episode_no + 1,
        campaign_discount_active=discount_active,
    )


def _accrue(state: State, agreement: Agreement, day: date, policy: Policy, repos: tuple[RepoRate, ...]) -> State:
    base = _interest_base_cents(state, policy)
    if base == 0:
        return state
    _base_rate, _stored_discount, effective = campaign_terms(
        agreement,
        day,
        repos,
        discount_active=state.campaign_discount_active,
        repo_fall=policy.repo_fall,
    )
    daily = daily_interest_rands(
        base,
        effective,
        divisor_days(day, agreement.product, policy.day_count),
        weight=accrual_weight(day, policy.day_count),
    )
    if state.in_default:
        room = _room_rands(state, policy)
        if daily > room:
            daily = room
        episode = _open_episode(state)
        episode_no = episode.episode_no if episode else state.unbilled_duplum_episode
        return replace(
            state,
            unbilled_duplum=state.unbilled_duplum + daily,
            unbilled_duplum_episode=episode_no,
        )
    return replace(state, unbilled_ordinary=state.unbilled_ordinary + daily)


def _bill_interest(state: State, day: date, policy: Policy) -> State:
    state = _bill_ordinary_interest(state, day)
    return _bill_duplum_interest(state, day, policy)


def _bill_ordinary_interest(state: State, day: date) -> State:
    if state.unbilled_ordinary == 0:
        return state
    cents = to_cents(state.unbilled_ordinary)
    state = replace(state, unbilled_ordinary=Decimal("0"))
    if cents == 0:
        return state
    return _add_charge(
        state,
        kind="interest",
        on=day,
        ex_vat_cents=cents,
        vat_cents=0,
        total_cents=cents,
        episode_no=None,
    )


def _bill_duplum_interest(state: State, day: date, policy: Policy) -> State:
    if state.unbilled_duplum == 0 and state.duplum_interest_counted_cents == 0:
        return state
    episode = _open_episode(state)
    if episode is not None:
        cents = min(to_cents(state.unbilled_duplum), _room_cents(state, policy, include_unbilled=False))
        accrued = episode.accrued_cents + cents
        episode = replace(episode, accrued_cents=accrued)
        state = replace(
            state,
            episodes=_replace_episode(state, episode),
            unbilled_duplum=Decimal("0"),
            duplum_interest_counted_cents=0,
        )
        episode_no = episode.episode_no
    else:
        cents = state.duplum_interest_counted_cents
        episode_no = state.unbilled_duplum_episode
        state = replace(
            state,
            unbilled_duplum=Decimal("0"),
            duplum_interest_counted_cents=0,
            unbilled_duplum_episode=None,
        )
    if cents <= 0:
        return state
    return _add_charge(
        state,
        kind="interest",
        on=day,
        ex_vat_cents=cents,
        vat_cents=0,
        total_cents=cents,
        episode_no=episode_no,
    )


def _clip_to_duplum(state: State, policy: Policy, total_cents: int) -> tuple[int, State]:
    if not state.in_default or not policy.count_vat_in_duplum:
        return total_cents, state
    room = _room_cents(state, policy, include_unbilled=False)
    charged = min(total_cents, room)
    return charged, state


def _consume_duplum(state: State, cents: int) -> State:
    episode = _open_episode(state)
    if episode is None or cents <= 0:
        return state
    updated = replace(episode, accrued_cents=episode.accrued_cents + cents)
    return replace(state, episodes=_replace_episode(state, updated))


def _levy_priced(
    state: State,
    *,
    kind: str,
    on: date,
    ex_vat_cents: int,
    vat_cents: int,
    total_cents: int,
    policy: Policy,
    vat_rate: Decimal,
    due_on: date | None = None,
) -> State:
    charged, state = _clip_to_duplum(state, policy, total_cents)
    if charged < total_cents:
        state = replace(
            state,
            clips=state.clips
            + (Clip(on, kind, total_cents, charged, "duplum"),),
        )
    if charged <= 0:
        return state
    if charged == total_cents:
        ex_vat, vat, total = ex_vat_cents, vat_cents, total_cents
    else:
        ex_vat, vat = split_inclusive(charged, vat_rate if policy.vat_registered else Decimal(0))
        total = charged
    episode = _open_episode(state) if state.in_default else None
    episode_no = episode.episode_no if episode is not None else None
    if episode is not None and policy.count_vat_in_duplum:
        state = _consume_duplum(state, total)
    elif episode is not None:
        state = _consume_duplum(state, ex_vat)
    return _add_charge(
        state,
        kind=kind,
        on=on,
        ex_vat_cents=ex_vat,
        vat_cents=vat,
        total_cents=total,
        episode_no=episode_no,
        due_on=due_on or on,
    )


def _priced_initiation(
    agreement: Agreement,
    day: date,
    policy: Policy,
    vat_rates: tuple[VatRate, ...],
) -> tuple[int, int, int]:
    """Booked ex-VAT fee plus VAT. The statutory formula is only for an unbooked agreement."""
    rate = vat_on(day, vat_rates) if policy.vat_registered else Decimal(0)
    if agreement.booked_initiation_ex_vat_cents is not None:
        return add_vat(agreement.booked_initiation_ex_vat_cents, rate)
    ex_vat, vat, total = initiation_fee(
        agreement.cash_advanced_cents,
        on=day,
        vat_rates=vat_rates,
        basis=policy.fee_cap_basis,
        vat_registered=policy.vat_registered,
    )
    if agreement.campaign_initiation_discount_cents:
        ex_vat, vat, total = apply_ex_vat_discount(
            ex_vat, rate, agreement.campaign_initiation_discount_cents
        )
    return ex_vat, vat, total


def _capitalise_initiation(
    state: State,
    agreement: Agreement,
    day: date,
    policy: Policy,
    vat_rates: tuple[VatRate, ...],
) -> State:
    """Add a capitalised initiation fee to unpaid principal before interest (§2, §7).

    The fee is added to the earliest principal slice so it is payable. How a
    capitalised fee is spread across instalments is not locked. That choice is
    recorded in the implementation note and is not a second rule.
    """
    if state.initiation_levied or day != agreement.advance_date or not agreement.initiation_capitalised:
        return state
    _ex_vat, vat, total = _priced_initiation(agreement, day, policy, vat_rates)
    if agreement.initiation_already_in_principal:
        # Decision 2. The ex-VAT fee is already inside principal. VAT is still
        # part of the settlement value.
        state = replace(state, initiation_levied=True)
        if vat <= 0:
            return state
        return _levy_priced(
            state,
            kind="initiation",
            on=day,
            ex_vat_cents=0,
            vat_cents=vat,
            total_cents=vat,
            policy=policy,
            vat_rate=vat_on(day, vat_rates) if policy.vat_registered else Decimal(0),
            due_on=day,
        )
    if total <= 0:
        return replace(state, initiation_levied=True)
    slices = list(state.principal_slices)
    earliest = min(range(len(slices)), key=lambda index: (slices[index].due_on, slices[index].sequence))
    slice_ = slices[earliest]
    slices[earliest] = PrincipalSlice(
        slice_.due_on,
        slice_.amount_cents + total,
        slice_.remaining_cents + total,
        slice_.sequence,
    )
    return replace(state, principal_slices=tuple(slices), initiation_levied=True)


def _levy_initiation(state: State, agreement: Agreement, day: date, policy: Policy, vat_rates: tuple[VatRate, ...]) -> State:
    if state.initiation_levied or day != agreement.advance_date or agreement.initiation_capitalised:
        return state
    ex_vat, vat, total = _priced_initiation(agreement, day, policy, vat_rates)
    # A deferred initiation fee is unpaid from the advance date, so s 126 allocates
    # it before principal, but it is not a default until the first principal due date.
    # Paying it upfront makes it due, and paid, on the advance date.
    due = day if agreement.initiation_paid_upfront else min(
        slice_.due_on for slice_ in state.principal_slices
    )
    state = _levy_priced(
        state,
        kind="initiation",
        on=day,
        ex_vat_cents=ex_vat,
        vat_cents=vat,
        total_cents=total,
        policy=policy,
        vat_rate=vat_on(day, vat_rates) if policy.vat_registered else Decimal(0),
        due_on=due,
    )
    return replace(state, initiation_levied=True)


def _levy_service(state: State, agreement: Agreement, day: date, policy: Policy, vat_rates: tuple[VatRate, ...], *, settle: bool) -> State:
    key = (day.year, day.month)
    if key in state.service_months_levied:
        return state
    is_month_end = day == month_end(day)
    if not settle and not is_month_end:
        return state
    advance_key = (agreement.advance_date.year, agreement.advance_date.month)
    opening_fraction: Decimal | None = None
    if key == advance_key:
        # §9: disbursement through the day before the first due date, over the
        # days in the disbursement month, capped at one monthly fee. Settlement
        # inside the opening month does not shorten that locked numerator.
        first_due = min(slice_.due_on for slice_ in state.principal_slices)
        opening_fraction = opening_service_fraction(agreement.advance_date, first_due)
        period_start = agreement.advance_date
        period_end = agreement.advance_date
        full_month = False
    else:
        period_start = date(day.year, day.month, 1)
        if settle and policy.terminal_service_fee == TerminalServiceFee.PRO_RATA:
            period_end = day
            full_month = False
        else:
            period_end = month_end(day)
            full_month = True
    if period_end < period_start:
        return state
    ex_vat, vat, total = service_fee_cents(
        on=day,
        period_start=period_start,
        period_end=period_end,
        monthly_cap_cents=policy.service_fee_monthly_cents,
        full_month=full_month,
        fraction=opening_fraction,
        vat_rates=vat_rates,
        basis=policy.fee_cap_basis,
        vat_registered=policy.vat_registered,
    )
    if agreement.campaign_service_discount_cents:
        rate = vat_on(day, vat_rates) if policy.vat_registered else Decimal(0)
        ex_vat, vat, total = apply_ex_vat_discount(
            ex_vat, rate, agreement.campaign_service_discount_cents
        )
    state = _levy_priced(
        state,
        kind="service",
        on=day,
        ex_vat_cents=ex_vat,
        vat_cents=vat,
        total_cents=total,
        policy=policy,
        vat_rate=vat_on(day, vat_rates) if policy.vat_registered else Decimal(0),
    )
    return replace(state, service_months_levied=state.service_months_levied + (key,))


def _levy_manual(state: State, event: ManualCharge, policy: Policy, vat_rates: tuple[VatRate, ...]) -> State:
    rate = vat_on(event.on, vat_rates) if policy.vat_registered else Decimal(0)
    if event.ex_vat_cents is not None and event.vat_cents is not None:
        if event.ex_vat_cents + event.vat_cents != event.total_cents:
            raise RuleError("charge", "Manual charge ex-VAT and VAT must sum to the total.")
        ex_vat, vat, total = event.ex_vat_cents, event.vat_cents, event.total_cents
    else:
        ex_vat, vat = split_inclusive(event.total_cents, rate)
        total = event.total_cents
    return _levy_priced(
        state,
        kind=event.kind,
        on=event.on,
        ex_vat_cents=ex_vat,
        vat_cents=vat,
        total_cents=total,
        policy=policy,
        vat_rate=rate,
    )


def _close_if_cured(state: State, day: date, policy: Policy) -> State:
    episode = _open_episode(state)
    if episode is None or not state.in_default or not _cured(state, day, policy):
        return state
    counted = min(to_cents(state.unbilled_duplum), _room_cents(state, policy, include_unbilled=False))
    closed = replace(
        episode,
        accrued_cents=episode.accrued_cents + counted,
        closed_on=day,
    )
    return replace(
        state,
        episodes=_replace_episode(state, closed),
        in_default=False,
        duplum_interest_counted_cents=counted,
        prior_duplum_accrued_cents=state.prior_duplum_accrued_cents + closed.accrued_cents,
        unbilled_duplum_episode=episode.episode_no,
    )


def _maybe_finish(
    state: State,
    agreement: Agreement,
    day: date,
    policy: Policy,
    vat_rates: tuple[VatRate, ...],
) -> State:
    """Settle only when principal, accrued interest, and this month's service fee are paid.

    A payment that clears the principal is not a settlement until the terminal
    service fee has been levied and collected. Charging that fee is the day-1
    full-month policy; a one-cent shortfall leaves the agreement open.
    """
    if state.status != "open" or state.principal_cents > 0:
        return state
    if any(charge.remaining_cents > 0 for charge in state.charges):
        return state
    suspense = state.suspense_cents
    state = replace(state, suspense_cents=0)
    state = _bill_interest(state, day, policy)
    state = _levy_service(state, agreement, day, policy, vat_rates, settle=True)
    if suspense:
        state = allocate_payment(state, suspense, as_of=day, settle=True).state
    cleared = (
        state.principal_cents == 0
        and all(charge.remaining_cents == 0 for charge in state.charges)
        and state.unbilled_ordinary == 0
        and state.unbilled_duplum == 0
    )
    if not cleared:
        return state
    episode = _open_episode(state)
    if episode is not None:
        closed = replace(episode, closed_on=day)
        state = replace(
            state,
            episodes=_replace_episode(state, closed),
            prior_duplum_accrued_cents=state.prior_duplum_accrued_cents + closed.accrued_cents,
        )
    return replace(
        state,
        status="settled",
        settled_on=day,
        in_default=False,
        unbilled_ordinary=Decimal("0"),
        unbilled_duplum=Decimal("0"),
    )


def _ordinary_payments(events: tuple[Event, ...]) -> tuple[Payment, ...]:
    """Receipts recognised at 00:00, in recognition order (§1)."""
    indexed = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, Payment) and event.purpose != "initiation_upfront"
    ]
    indexed.sort(key=lambda pair: (pair[1].sequence, pair[0]))
    return tuple(event for _, event in indexed)


def _preview_receipts(state: State, payments: tuple[Payment, ...], day: date, policy: Policy) -> State:
    """Apply flag-date receipts to amounts already due, without choosing a prepayment rule."""
    preview = state
    for payment in payments:
        preview = allocate_payment(
            preview,
            payment.cents,
            as_of=day,
            prepayment=policy.prepayment_choice,
            apply_prepayment=False,
        ).state
    return preview


def _fold_day(
    state: State,
    agreement: Agreement,
    day: date,
    events: tuple[Event, ...],
    policy: Policy,
    repos: tuple[RepoRate, ...],
    vat_rates: tuple[VatRate, ...],
    *,
    settle: bool,
) -> State:
    if state.status != "open":
        return state
    for event in events:
        if isinstance(event, LaybyeHold):
            state = replace(state, laybye_hold_cents=event.hold_cents)
    # A capitalised initiation fee is part of principal at 00:00 on the advance date,
    # so the day's interest and any later ceiling include it.
    state = _capitalise_initiation(state, agreement, day, policy, vat_rates)
    receipts = _ordinary_payments(events)
    # The morning check sees a flag-date receipt. Interest for the day still uses
    # the principal from before that receipt is posted. An episode that is already
    # open stays open until the receipt is actually allocated, so a cure still
    # closes it and counts this day's in-duplum interest.
    morning_overdue = _overdue(_preview_receipts(state, receipts, day, policy), day, policy)
    if morning_overdue or _open_episode(state) is not None:
        state = _open_default(state, day, agreement)
    else:
        state = replace(state, in_default=False)
    state = _accrue(state, agreement, day, policy, repos)
    state = _levy_initiation(state, agreement, day, policy, vat_rates)
    upfront = tuple(event for event in events if isinstance(event, Payment) and event.purpose == "initiation_upfront")
    manuals = tuple(event for event in events if isinstance(event, ManualCharge))
    for payment in upfront:
        state = allocate_payment(
            state,
            payment.cents,
            as_of=day,
            prepayment=policy.prepayment_choice,
        ).state
    if settle or day == month_end(day):
        state = _bill_interest(state, day, policy)
    state = _levy_service(state, agreement, day, policy, vat_rates, settle=settle)
    for event in manuals:
        state = _levy_manual(state, event, policy, vat_rates)
    for payment in receipts:
        state = allocate_payment(
            state,
            payment.cents,
            as_of=day,
            prepayment=policy.prepayment_choice,
        ).state
    # Bill a terminal service fee before default is closed, so a settlement on a
    # default day still consumes in-duplum room. _maybe_finish only acts once
    # principal and already-billed charges are clear.
    state = _maybe_finish(state, agreement, day, policy, vat_rates)
    state = _close_if_cured(state, day, policy)
    return replace(state, as_of=day)


def _events_on(events: tuple[Event, ...], day: date) -> tuple[Event, ...]:
    return tuple(event for event in events if event.on == day and not isinstance(event, Settlement))


def _fold_until(
    agreement: Agreement,
    events: tuple[Event, ...],
    until: date,
    policy: Policy,
    repos: tuple[RepoRate, ...],
    vat_rates: tuple[VatRate, ...],
    *,
    settle_on: date | None,
) -> State:
    _require_default_config(policy)
    if until < agreement.advance_date:
        raise RuleError("term", "Cannot fold to a date before the advance.")
    if agreement.product not in (Product.MICRO, Product.PERSONAL):
        raise RuleError("product", "Only micro and personal agreements accrue on the loan ledger.")
    state = _initial(agreement)
    day = agreement.advance_date
    while day <= until:
        state = _fold_day(
            state,
            agreement,
            day,
            _events_on(events, day),
            policy,
            repos,
            vat_rates,
            settle=settle_on == day,
        )
        if state.status != "open":
            return state
        day += timedelta(days=1)
    return state


def _component_totals(state: State) -> tuple[tuple[str, int], ...]:
    totals: dict[str, int] = {}
    for charge in state.charges:
        if charge.remaining_cents:
            totals[charge.kind] = totals.get(charge.kind, 0) + charge.remaining_cents
    if state.principal_cents:
        totals["principal"] = state.principal_cents
    return tuple(sorted(totals.items()))


def quote_settlement(
    agreement: Agreement,
    events: tuple[Event, ...] = (),
    *,
    as_of: date,
    delivered_on: date | None = None,
    policy: Policy | None = None,
    repos: tuple[RepoRate, ...] = (),
    vat_rates: tuple[VatRate, ...] = DEFAULT_VAT,
    holidays: frozenset[date] = frozenset(),
) -> SettlementQuote:
    """Section 125(2) amount, as of ``as_of``, made bindable by s 113.

    Day-1 micro and personal agreements are small or intermediate, so the
    s 125(2)(c) large-agreement early-termination charge is zero. A large
    agreement is rejected at construction rather than quoted with an invented charge.
    """
    policy = policy or Policy()
    delivered = delivered_on or as_of
    if delivered < as_of:
        raise RuleError("quote", "A settlement statement cannot be delivered before its as-of date.")
    size = agreement_size(agreement.cash_advanced_cents, mortgage=agreement.mortgage)
    if size == "large":
        raise RuleError(
            "early-termination-unlocked",
            "The s 125(2)(c) three-month charge is not locked. Day-1 agreements must stay below R250,000.",
        )
    state = _fold_until(
        agreement,
        tuple(event for event in events if event.on <= as_of),
        as_of,
        policy,
        repos,
        vat_rates,
        settle_on=as_of,
    )
    components = _component_totals(state)
    interest = sum(amount for kind, amount in components if kind == "interest")
    fees = sum(amount for kind, amount in components if kind not in ("interest", "principal"))
    total = payoff_cents(state)
    return SettlementQuote(
        as_of=as_of,
        delivered_on=delivered,
        valid_until=binding_until(delivered, holidays),
        principal_cents=state.principal_cents,
        interest_cents=interest,
        fee_cents=fees,
        early_termination_cents=0,
        total_cents=total,
        agreement_size=size,
        components=components,
    )


def execute_settlement(
    agreement: Agreement,
    quote: SettlementQuote,
    payment_cents: int,
    paid_on: date,
    events: tuple[Event, ...] = (),
    *,
    policy: Policy | None = None,
    repos: tuple[RepoRate, ...] = (),
    vat_rates: tuple[VatRate, ...] = DEFAULT_VAT,
) -> RunResult:
    """Accept the quoted rand amount inside the s 113 window and stop further accrual.

    A short payment, or a payment after the window, is an ordinary s 126 payment
    and does not settle the agreement. Inside the window the quoted total does not
    grow with later interest; the difference from a freshly computed payoff is waived.
    """
    policy = policy or Policy()
    in_window = quote.delivered_on <= paid_on <= quote.valid_until
    if payment_cents >= quote.total_cents and in_window:
        naive = quote_settlement(
            agreement,
            events,
            as_of=paid_on,
            delivered_on=paid_on,
            policy=policy,
            repos=repos,
            vat_rates=vat_rates,
        )
        state = _fold_until(
            agreement,
            tuple(event for event in events if event.on <= quote.as_of),
            quote.as_of,
            policy,
            repos,
            vat_rates,
            settle_on=quote.as_of,
        )
        state = allocate_payment(state, quote.total_cents, as_of=quote.as_of, settle=True).state
        surplus = payment_cents - quote.total_cents
        if state.principal_cents != 0 or any(charge.remaining_cents > 0 for charge in state.charges):
            raise RuleError(
                "quote-mismatch",
                "The quoted total did not clear the as-of balances. Refusing to mark the agreement settled.",
            )
        episode = _open_episode(state)
        if episode is not None:
            closed = replace(episode, closed_on=paid_on)
            state = replace(
                state,
                episodes=_replace_episode(state, closed),
                prior_duplum_accrued_cents=state.prior_duplum_accrued_cents + closed.accrued_cents,
            )
        waived = max(0, naive.total_cents - quote.total_cents)
        state = replace(
            state,
            status="settled",
            settled_on=paid_on,
            as_of=paid_on,
            in_default=False,
            suspense_cents=state.suspense_cents + surplus,
            waived_cents=waived,
            unbilled_ordinary=Decimal("0"),
            unbilled_duplum=Decimal("0"),
        )
        return RunResult(state)
    # Not a binding settlement. Fold forward and treat the money as an ordinary payment.
    ordinary = events + (Payment(paid_on, payment_cents),)
    state = _fold_until(agreement, ordinary, paid_on, policy, repos, vat_rates, settle_on=None)
    return RunResult(state)


def run(
    agreement: Agreement,
    events: tuple[Event, ...] = (),
    *,
    until: date,
    policy: Policy | None = None,
    repos: tuple[RepoRate, ...] = (),
    vat_rates: tuple[VatRate, ...] = DEFAULT_VAT,
    settle_on: date | None = None,
) -> RunResult:
    """Fold ``agreement`` from the advance date through ``until`` inclusive."""
    policy = policy or Policy()
    if any(isinstance(event, Settlement) for event in events):
        raise RuleError(
            "settlement",
            "Pass a settlement through execute_settlement so the s 113 window is checked explicitly.",
        )
    state = _fold_until(agreement, events, until, policy, repos, vat_rates, settle_on=settle_on)
    return RunResult(state)


def charge_remaining(state: State, kind: str) -> int:
    return sum(charge.remaining_cents for charge in state.charges if charge.kind == kind)


def episode_accrued(state: State, episode_no: int = 1) -> int:
    for episode in state.episodes:
        if episode.episode_no == episode_no:
            return episode.accrued_cents
    raise RuleError("duplum", f"No duplum episode {episode_no}.")
