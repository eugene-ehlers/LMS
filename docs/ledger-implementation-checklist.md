# DRAFT — Layer 1 implementation checklist

**Status: draft sketch.** This is not a locked decision and it is not production code. Behaviour comes only from [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md). Table shapes and gap ids come from [account-balance-transaction-model.md](account-balance-transaction-model.md). Where this file shows a signature, the body is not specified beyond the lock it must obey and the gap it must not paper over.

Do not fill a gap in this list by choosing a reading.

---

## 1. Data structures to create

No application code. Migration sketches only, matching section 2 of the design note.

| # | Structure | Locked content it must hold | Must not |
| --- | --- | --- | --- |
| D1 | `customer_default_terms` | `leniency_days`, `full_payment_threshold_percent`, per organisation + `person_id` | A default number when null |
| D2 | `provider_election` | Day count, deferred-initiation interest choice, repo policy, VAT exclusive/inclusive, disbursement adjustment, external-schedule switch, prepayment schedule choice, `calendar_zone` | A platform default for repo policy or calendar zone |
| D3 | `statutory_parameter`, `tariff_row` | Cited caps and tariffs with effective dates | Compiled rand amounts |
| D4 | `loan_account`, `laybye_account` | Parent/child, `structure` `cash_deposit` or `insurance`, one open child | A secured-loan kind for the pair |
| D5 | `section_124_authority` | `signed_in_life`, opaque `evidence_ref` | An evidence test (T27) |
| D6 | `identity_freeze` | Name, ID number, service address, insert-only | A later update from Enigma |
| D7 | `agreement_version` | Base rate, initiation treatment, frequencies, quote date, schedule origin, disclosed AER column | An AER formula (T26) |
| D8 | `pricing_concession` | Base and discount stored separately, date range | A single blended rate as the only stored figure |
| D9 | `schedule_version`, `schedule_line` | Principal slice, service fee, initiation, credit life, other monthly fee | Other monthly fee inside the principal slice |
| D10 | `ledger_transaction`, `ledger_entry` | `value_date` and `recognised_at` as separate columns; reversal points at the original | Setting a reversal’s `value_date` from the reversal’s own `recognised_at` |
| D11 | `accrual_decision` | Net principal, gross principal, base ppm, discount ppm, charged ppm, `duplum_policy` | Clipping while `duplum_policy = unsigned` |
| D12 | `default_episode` | Flag date, due date, copied leniency and threshold, ceiling | Opening an episode on any rule other than lock 6 |
| D13 | `payment_instruction`, `payment_leg` | Legs to the loan, the lay-by, or both | An invented same-day order (T2) |
| D14 | `client_statement` | One header per organisation + person + period | A per-loan statement table |
| D15 | `balance_snapshot` | Cache only | Serving a snapshot that ignores a reversal of an earlier value date |

Component codes on loan entries: `principal`, `interest`, `initiation_fee`, `service_fee`, `credit_life`, `other_monthly_fee`, `default_admin`, `collection_cost`, `unapplied_credit`. Lay-by: `consumer_funds_held`.

---

## 2. Function signatures

Draft signatures for the later engine. They return structured results or fail closed. They do not contain a hidden default for any T-id.

```python
def derive_originating_value_date(
    recognised_at: datetime,
    calendar_zone: str | None,
) -> date:
    """Lock 1. Fail closed if calendar_zone is missing (T29).
    The result is 00:00 on that civil date. Do not accept a caller-supplied value date.
    """

def derive_reversal_value_date(original_value_date: date) -> date:
    """Lock 1. Return original_value_date. Do not use the reversal's recognised_at.
    Do not define a replay of days between the two timestamps (T1).
    """

def net_balance_cents(principal_cents: int, laybye_hold_cents: int) -> int:
    """Lock 4 names this difference as the interest base.
    Do not substitute 'outstanding balance' (T6). If a caller cannot show the
    two phrases are the same quantity, do not accrue.
    """

def charged_rate_ppm(
    base_ppm: int,
    discount_ppm: int,
    on_date: date,
    flag_date: date | None,
    in_leniency_window: bool,
) -> int:
    """Locks 3 and 6. Discount applies through leniency.
    On and after flag_date the result is base_ppm.
    A cured episode must not restore discount_ppm.
    Zero is a valid result. Do not divide by the result.
    Do not add a penalty above the contractual rate (T5).
    """

def accrue_one_day(
    net_principal_cents: int,
    charged_ppm: int,
    day_count: str,
    weight: object | None,
) -> AccrualDecision:
    """Lock 5: daily. weight is None until T28 is locked.
    If day_count is actual_actual or thirty_360 and weight is None, fail closed.
    Do not embed a 30/360 or actual/actual formula.
    duplum_policy stays 'unsigned' and does not change the computed amount (lock 7).
    """

def bill_half_up(unbilled: Decimal, affordability_cap_cents: int | None) -> int:
    """Lock 17. Half-up to cents.
    If the cent result would exceed affordability_cap_cents, fail closed (T25).
    Do not decide whether a daily accrual is a billing event (T24).
    """

def allocate_section_126(
    amount_cents: int,
    due_interest_cents: int,
    due_fees: Sequence[FeeDue],
    principal_cents: int,
) -> Allocation:
    """Lock 8. Interest, then fees, then principal.
    FeeDue includes a separate initiation fee and excludes a capitalised one.
    If more than one fee is due and their order would change the result, fail closed (T14).
    """

def amount_received_for_due_date(
    due_on: date,
    payments: Sequence[Payment],
) -> int | None:
    """Lock 6 needs this figure. Return None when attribution is ambiguous (T10).
    A None result fails the default test closed. Do not assign receipts oldest-due-first.
    """

def threshold_instalment_cents(line: ScheduleLine) -> int:
    """Lock 6. principal slice + service fee + non-capitalised initiation + credit life
    that share line.due_on.
    Do not add interest (T11) unless a later lock says debited interest is included.
    """

def flag_default(
    due_on: date,
    leniency_days: int | None,
    threshold_percent: Decimal | None,
    received_cents: int | None,
) -> bool:
    """Lock 6. Any None argument fails closed.
    Flag date = due_on plus leniency_days calendar days, weekends and holidays included.
    Flag only when received_cents is below the threshold.
    A payment with value_date equal to the flag date is part of received_cents
    only if the caller can show the morning check has seen it (T3). Otherwise fail closed.
    """

def open_episode(flag: DefaultFlag, unpaid_principal_cents: int) -> DefaultEpisode:
    """Lock 7. Ceiling is unpaid principal including pre-default capitalised initiation.
    counts_toward_duplum is false for the charges that caused the flag.
    Do not clip.
    """

def cure_episode(episode_id: UUID) -> None:
    """Lock 7. Close the episode. Do not reset a counter by a partial payment.
    Do not restore a campaign discount.
    """

def opening_month_service_fee(
    contractual_fee_cents: int,
    disbursement: date,
    first_due: date,
    days_in_month: int,
    inclusive_days: int | None,
    is_opening_month: bool,
    is_settlement_month: bool,
) -> int | None:
    """Lock 9. None means fail closed.
    After the opening month, including a later settlement month, return the full fee
    subject to the configured ex-VAT monthly cap (default exclusive).
    If is_opening_month and inclusive_days is None, return None (T15).
    If is_opening_month and is_settlement_month, return None (T16).
    Inclusive VAT returns None (T17).
    """

def interest_base_cents(
    net_balance: int,
    deferred_initiation_cents: int,
    interest_on_deferred_initiation: bool,
) -> int | None:
    """Lock 10. False: return net_balance and ignore deferred_initiation_cents.
    True: return None (T18). Do not add the fee into the base by assumption.
    """

def rate_after_repo(
    policy: str | None,
    contract_ppm: int,
    statutory_max_ppm: int | None,
) -> int:
    """Lock 11. None policy fails closed.
    contract_rate -> contract_ppm.
    lower_of_contract_and_statutory -> min of the two, and the caller must emit
    a section 104 notice record. Missing statutory_max_ppm fails closed.
    """

def apply_credit_life(
    settlement_cents: int,
    proceeds_cents: int,
    hold_cents: int,
    signed_in_life: bool,
    structure: str,
    beneficiary_named: bool,
) -> CreditLifeResult:
    """Lock 4. Proceeds pay the loan first (section 126).
    If not signed_in_life: do not reduce the hold; the hold stays with the estate.
    If signed_in_life and structure == 'cash_deposit': hold covers the shortfall;
    surplus hold goes to the estate.
    If structure == 'insurance': return an unresolved result (T8). Do not pick a payee.
    """

def apply_funeral(beneficiary_person_id: str, amount_cents: int) -> Payout:
    """Lock 4. Pay the beneficiary. No loan entry. No lay-by entry."""

def consolidate_or_settle(hold_cents: int, settlement_cents: int) -> bool:
    """Lock 4. True only when hold_cents >= settlement_cents."""

def schedule_after_late_disbursement(
    policy: str,
    quoted: Schedule,
    disbursement: date,
) -> Schedule:
    """Lock 13. recalculate_instalment uses actual disbursement date and remaining term.
    keep_instalment keeps the quoted instalment.
    Do not write off a residual (T31). Early settlement is the ordinary settle path.
    """

def schedule_after_partial_prepayment(
    policy: str | None,
    current: Schedule,
) -> Schedule | None:
    """Lock 13. None policy returns None (T19). Do not apply the 'prefer same instalment'
    sentence as a default. shorten_term and drop_instalment are the only stored choices.
    """

def count_subsequent_short_term(organisation_id: str) -> int | None:
    """Lock 13. Group by organisation only.
    Return None until T20 (calendar year and consumer) is locked. Do not count.
    """

def freeze_identity(
    name: str | None,
    id_number: str | None,
    service_address: str | None,
) -> IdentityFreeze | None:
    """Lock 16. When all three values are present, store them and never update the row.
    When any value is missing, do not invent a waiver and do not invent a hard stop (T23).
    Return None and leave booking unwritten until that gap is locked.
    """

def require_enigma(status: str, timed_out: bool) -> None:
    """Lock 15. Raise on timeout. Raise when the caller has already classed the status
    as ambiguous. Do not decide which statuses are ambiguous (T22).
    """
```

`FeeDue`, `ScheduleLine`, `AccrualDecision`, `Allocation`, `CreditLifeResult`, `Payout`, `DefaultFlag`, `DefaultEpisode`, `IdentityFreeze` and `Schedule` are draft records. Their fields are the columns in section 1 of this checklist. They are not an API contract.

---

## 3. Invariants to test

Build these as database checks or as pure tests against a fixture ledger. Expected results are the locks, not sample business numbers. Do not hard-code a leniency day count, a threshold percent, a VAT rate, or a day-count weight.

| # | Assert |
| --- | --- |
| I1 | Originating `value_date` equals the civil date of `recognised_at` in the configured zone, at 00:00. Missing zone rejects the insert. |
| I2 | Reversal `value_date` equals the original `value_date` even when `recognised_at` falls on a later civil day. The original row is unchanged. |
| I3 | Null `leniency_days` or null `full_payment_threshold_percent` makes `flag_default` fail. |
| I4 | Flag date uses calendar days. A weekend or public holiday inside the window is counted. |
| I5 | An episode does not open when received cents are at or above the threshold. It opens when they are below. |
| I6 | Campaign discount still applies on a date inside leniency, does not apply on the flag date, and does not apply after cure. |
| I7 | A zero base rate and a 100% discount both produce a zero charged rate and do not raise. |
| I8 | One `service_fee_debit` per parent per calendar month. A child insert of that kind fails. |
| I9 | `consolidate_or_settle` is false when hold is one cent under the settlement balance. |
| I10 | Credit life with `signed_in_life` false leaves `consumer_funds_held` unchanged. |
| I11 | Funeral payout inserts no loan and no lay-by entry. |
| I12 | `accrue_one_day` with `duplum_policy` unsigned posts the computed amount unchanged. |
| I13 | Episode ceiling equals unpaid principal at flag, including initiation capitalised before that date, and a later payment does not update the ceiling row. |
| I14 | A payment allocation puts zero cents to principal while due interest remains, and zero cents to principal while due fees remain after interest is cleared. |
| I15 | Capitalised initiation: `initiation_fee` balance is 0 and principal includes the fee. Separate: principal does not include the fee. |
| I16 | Null `repo_rate_policy` rejects accrual. |
| I17 | `default_admin_debit` and `collection_cost_debit` reject when no tariff row covers `value_date`. |
| I18 | `other_monthly_fee` never appears inside `principal_slice_cents`. |
| I19 | Half-up: a billed amount of n + 0.5 cents becomes n + 1 cent for a positive amount. A second billing site that rounds differently fails review. |
| I20 | `identity_freeze` update fails. |
| I21 | Statement uniqueness is `(organisation, person, period)`, not `loan_id`. |
| I22 | `day_count` outside `actual_actual` and `thirty_360` rejects. Accrual without a locked weight rejects (T28). |
| I23 | Subsequent-short-term helper returns None (not a count) until T20 is locked. |

---

## 4. Technical open questions

These are the gaps in the design note. None is answered here.

| Id | Question that blocks an implementation step |
| --- | --- |
| T1 | What should a reader of an earlier value date do when a reversal of that date is recognised later? |
| T2 | In what order are two 00:00 events on the same value date applied? |
| T3 | When does the morning default check run relative to a payment recognised later that day with the flag date? |
| T4 | Which fees other than initiation use the capitalised versus section 126 treatment? |
| T5 | Is the penalty cap the base rate or the discounted rate? |
| T6 | Is the daily interest base net principal, or the outstanding balance if that is wider? |
| T7 | Which NCA category applies to the single loan-plus-lay-by contract? |
| T8 | Who is paid when an insurance-structured lay-by has a named beneficiary, and when it does not? |
| T9 | What posts during the deposit period before disbursement? |
| T10 | How is “received for that due date” measured under section 126? |
| T11 | Does debited interest enter the threshold instalment? |
| T13 | Which statement fields show a post-default accrual as capitalised, and which three section 103(5) edges stay unsigned? |
| T14 | How are two due fees ordered? |
| T15 | What is the numerator of the opening-month fraction? |
| T16 | Which service-fee rule wins when settlement is in the opening month? |
| T17 | What VAT rate and cap arithmetic apply when the provider elects inclusive? |
| T18 | What is added to the interest base when deferred-initiation interest is permitted? |
| T19 | What happens if `prepayment_schedule_policy` is null? |
| T20 | Does the subsequent-loan count also filter by consumer and calendar year? |
| T21 | Are default administration and collection costs the further monthly fee, or separate components plus that fee? |
| T22 | Which Enigma outcomes are timeout or ambiguous? |
| T23 | Does booking stop when name, ID number, or service address is absent? |
| T24 | Is each daily accrual billed, or only a later billing event? |
| T25 | What happens when half-up exceeds the aligned affordability figure? |
| T26 | How is the annual equivalent rate computed? |
| T27 | What evidence sets `signed_in_life`? |
| T28 | What are the day weights for `actual_actual` and for `thirty_360`? |
| T29 | Which timezone defines the calendar day? |
| T31 | What amount is a “small” residual? |
| T33 | What dates bound a client statement? |
| T34 | How is the next due date computed, including month-end? |
| T35 | What happens when concessions overlap, or the discount exceeds the base? |

T12 is unused so the ids match the design note.

---

## 5. Implementation order once gaps are left closed

Work that does not need a gap answer:

1. Tables D1–D15 with nulls failing closed where the lock says so.
2. `derive_originating_value_date`, `derive_reversal_value_date`, `freeze_identity`, `require_enigma`.
3. Section 126 allocator that fails closed on an ambiguous fee tier (I14, T14).
4. Campaign charged-rate function (I6, I7).
5. Default flag function that fails closed on missing inputs and on T10/T3 (I3–I5).
6. Episode open and cure without clipping (I12, I13).
7. Credit-life and funeral posters that stop on T8 and on missing section 124 (I10, I11).
8. Service-fee function that returns the full post-opening fee and fails closed on T15–T17.
9. Statement header uniqueness (I21).

Work that stays refused until the matching T-id is locked: day-count weights (T28), inclusive VAT (T17), interest on deferred initiation (T18), residual write-off (T31), subsequent-loan counter (T20), prepayment reschedule when unset (T19), insurance-lay-by payee (T8), deposit-period fees (T9).
