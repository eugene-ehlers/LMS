# Day-1 calculation engine

Pure functions in `src/lms/calc/`. No ledger, no configuration store, no Enigma client, and no servicing orchestration. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) (28 October 2026) is the source of truth. This note does not change a locked rule.

## Stable signatures

```text
nominal_annual_rate(periodic_rate, periods_per_year) -> Decimal
periods_per_year(product) -> int
opening_service_fraction(advance_date, first_due) -> Decimal
accrual_weight(day, day_count) -> int
personal_annual_rate(day, margin, repos, *, advance_date, repo_fall) -> Decimal
campaign_terms(agreement, day, repos=(), *, discount_active, repo_fall=None)
    -> (base_rate, stored_discount, effective_rate)
daily_interest_rands(base_cents, periodic_rate, divisor, *, weight=1) -> Decimal
interest_for_dates(*, base_cents, agreement, start, end, repos=(), day_count=ACTUAL, repo_fall=None) -> Decimal
service_fee_cents(*, on, period_start, period_end, monthly_cap_cents=6000, full_month=False,
                   fraction=None, vat_rates, basis, vat_registered=True) -> (ex_vat, vat, total)
allocate_payment(state, cents, *, as_of, prepayment=None, apply_prepayment=True, settle=False) -> Allocation
run(agreement, events=(), *, until, policy=None, repos=(), vat_rates=DEFAULT_VAT, settle_on=None) -> RunResult
quote_settlement(agreement, events=(), *, as_of, delivered_on=None, policy=None, ...) -> SettlementQuote
execute_settlement(agreement, quote, payment_cents, paid_on, events=(), *, policy=None, ...) -> RunResult
```

`Policy.leniency_days`, `Policy.full_payment_threshold_percent`, and `Policy.repo_fall` default to `None` and fail closed (`leniency-unset`, `threshold-unset`, `repo-choice-unset`). `Policy.prepayment_choice` defaults to `None` and fails closed (`prepayment-choice-unset`) only when a receipt would reduce principal that is not yet due. `DayCount.THIRTY_360` is the 30/360 convention. `RepoFallChoice` is `contract_rate_continues` or `lower_of_contract_and_cap`. `PrepaymentChoice` is `shorten_term` or `drop_instalment`.

`Agreement.initiation_capitalised` defaults to false. Worked examples that still use one day of leniency and a 100% threshold pass those numbers in. The engine does not.

## Test result

`PYTHONPATH=src python3 -m pytest` — **30 passed** on 28 October 2026 at 08:34 SAST.

The new pins are in `tests/test_day1_engine.py`: unset leniency and threshold, the flag-date morning check, calendar-day leniency across a weekend and Freedom Day, a capitalised initiation fee inside the next ceiling, actual/actual and 30/360, the repo choice failing closed, the simple nominal annual rate, the fee-bucket order, and a zero rate with a zero service fee.

## Raised, not solved

These are gaps. They are not new rules.

- **§5.** Both actual/actual and standard 30/360 must be available, and a 360-day year is not required for Day-1. The engine keeps actual/actual as the unset day-count and makes 30/360 selectable. It does not delete either sentence. The February weight (the last day of February carries enough day-counts for the month to equal 30, and the 31st carries none) is this engine's reading of "standard 30/360" so a full month equals the stated rate. The locked file does not say which calendar day carries those counts. `DayCount.FIXED` is still regulation 40's 30-day month and 365-day year. It is not 30/360.
- **§11.** A repo rise is not specified. Neither choice produces a rate above the contract rate struck on the advance date. The section 104 notice is not produced here.
- **§7.** Three section 103(5) edges remain unnamed. The Nedbank ceiling clip stays on. This note does not name the edges and does not treat VAT-in-the-cap as one of them.
- **§8 and §13.** The locked file does not give the arithmetic of "shorten the term" or "drop the instalment". When the caller has already chosen, `shorten_term` reduces the latest unpaid future slice and `drop_instalment` reduces the earliest. That direction is not a locked formula. Due principal does not need the choice.
- **§9.** "First payment due" is read as the earliest principal-slice due date. The opening fraction is capped at 1 because the monthly maximum is one fee. Settlement inside the opening month does not shorten the locked numerator. The locked file does not say to stop the numerator on the settlement date.
- **§2.** How a capitalised initiation fee is spread across instalments is not specified. The engine adds the consumer total to the earliest principal slice. It does not keep a section 102 list. `initiation_capitalised=True` means the caller states that capitalisation is permitted. Short-term and unsecured still default to false.
- **§1 and regulation 40.** A flag-date receipt is visible to the morning default check. That day's interest is still calculated on the principal from before the receipt is posted. The locked file does not say the receipt also reduces that day's interest.
- **§6 with leniency of 0.** The morning check uses amounts already levied. A charge levied later the same day is not in that morning bundle. The engine does not run a second default test after the day's levy.
- **§3.** Fee-discount fall-away is not locked. Fee discounts stay in place. A discount larger than the base rate produces an effective rate of 0%. The locked file describes a 0% campaign, not a negative rate.
- **§9 and §19.** §9 locks rand maxima as excluding VAT by default, with an inclusive election. §19 says an unset VAT election fails closed. The engine keeps the §9 exclusive default. It does not fail closed on that election.
- **§10 and §19.** §10 locks "no interest" as the default for a deferred initiation fee. §19 says unset values fail closed. The engine keeps the §10 default of no interest. It does not fail closed on that choice.
- **§17.** What happens when half-up rounding would push an instalment above an affordability figure is not specified. The engine rounds half-up and does not compare the result with an affordability figure.
- **§18.** A caller can still post a manual charge total with no tariff row. The engine does not invent tariff columns and does not hard-code a magistrates' court tariff.
- **§4.** "Lay-by balance at least the settlement balance" is not given a second formula, and the comparison is not placed inside or outside the section 113 window. Consolidation is not implemented. The section 125 total remains the only settlement total.
- **Out of scope, still locked.** Statements (§12), payment-frequency date generation (§14), identity freeze (§16), reversals (§1), the decision engine and restructuring (§13), and credit-life, death, and funeral posting (§4, §6) are not in this calculator.
