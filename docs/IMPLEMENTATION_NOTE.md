# Implementation note

Storage for organisation and product elections, statutory reference data, the Johannesburg day boundary, and the append-only audit log. Calculation formulas, ledger journals, the Enigma client, and servicing orchestration are not in this change.

`docs/LOCKED_DECISIONS.md` remains the source of truth. This note records what is now stable, what a caller can invoke, and the gaps that are still open.

## Stable tables and columns

`lms.cfg_organisation_settings`, one row per Enigma organisation. A product column of the same name overrides. Null is unset. It is not zero, 100 percent, `none`, or `exclusive`.

| Column | Allowed values | Lock |
| --- | --- | --- |
| `leniency_days` | integer, null or `>= 0` | Decision 6. Calendar days. |
| `full_payment_threshold_percent` | `numeric(6,3)`, null or `> 0` and `<= 100` | Decision 6. |
| `base_rate`, `discount_rate` | both null, or both set with `discount_rate <= base_rate` and each `>= 0` | Decision 3. Inherited as a pair. |
| `interest_on_deferred_initiation` | null, `none`, `permitted` | Decision 10 and decision 19. |
| `repo_rate_fall` | null, `contract_rate`, `lower_of_contract_and_cap` | Decision 11 and decision 19. |
| `day_count_code` | null, `actual_actual`, `thirty_360` | Decision 5. |
| `vat_on_rand_maxima` | null, `exclusive`, `inclusive` | Decision 9 and decision 19. |
| `late_disbursement` | null, `adjust_instalment`, `keep_instalment` | Decision 13 and decision 19. |
| `partial_prepayment` | null, `shorten_term`, `drop_instalment` | Decision 13 and decision 19. |

`lms.cfg_product_terms` carries the same elections, all nullable. `initiation_capitalised boolean NOT NULL DEFAULT false` is decision 2's Day-1 default, not a fail-closed election. `payment_frequency` is nullable and references `lms.ref_payment_frequency` (`weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual`, decision 14). A null frequency does not fail closed. The lock does not say it must.

`lms.ref_interest_cap`, `lms.ref_service_fee_cap`, `lms.ref_initiation_fee_cap`, `lms.ref_reference_rate`, and `lms.ref_tariff_amount` stay effective-dated. `ref_tariff_amount` is empty. A posting that needs a missing cap, a missing confirmed repo rate, or a missing tariff row fails. An interest accrual does not require a tariff row.

`lms.audit_event.recognition_sequence` is assigned by `lms.seal_audit_event` under the existing per-organisation advisory lock. `lms.audit_chain_head.last_sequence` stores the last value. The hash canonical includes that sequence. Callers cannot choose it.

`lms.ref_interpretation_choice` for `short_term_ordinal` is `per_organisation_and_calendar_year` (decision 13). The alternative recorded beside it is `lifetime_with_organisation`.

## Signatures

The calculation engine and the servicing layer can call these. They do not call Enigma.

```text
resolve_customer_settings(organisation, product) -> ResolvedCreditSettings
campaign_rate(base_rate, discount_rate, *, in_default=False, discount_fallen_away=False) -> Decimal
is_in_default(*, due_on, value_date, leniency_days, received_cents, instalment_cents, threshold_percent) -> bool
is_in_default_at_morning_check(*, due_on, check_on, leniency_days, receipts, instalment_cents, threshold_percent) -> bool
receipts_visible_at_morning_check(receipts, *, flag_on, due_on) -> tuple
order_recognised_events(receipts) -> tuple
nominal_annual_rate(periodic_rate, periods_per_year) -> Decimal
interest_bearing_cents(*, principal_cents, capitalised_initiation_cents, deposit_hold_cents, charge_interest_on_initiation) -> int
duplum_base_cents(*, cash_balance_cents, capitalised_initiation_cents) -> int
require_reference_for_posting(*, interest_cap_present, repo_annual, repo_required, tariff_cents, tariff_required) -> None
resolve_charge(pin, *, on, statutory_monthly, statutory_annual, repo_annual, in_default=False, discount_fallen_away=False) -> ResolvedCharge
value_date(instant) -> date
value_instant(day) -> datetime
opening_service_fee_cents(monthly_cents, disbursed_on, first_due_on) -> int
```

SQL the same transaction runs, in `src/lms_config/context.py`: `CUSTOMER_SETTINGS_SQL`, `TARIFF_SQL`, `SHORT_TERM_ORDINAL_SQL`, `INTEREST_CAP_SQL`, `REFERENCE_RATE_SQL`. `ENGINE_READ_STEPS` is the order. The transaction is `REPEATABLE READ`. A suspended enrolment fails closed at the Enigma boundary. This repository does not make that call.

`is_in_default_at_morning_check` counts a receipt whose Johannesburg value date is on or before the flag date and whose `due_on` is the contractual due date. A receipt at 23:59 SAST on the flag date counts. A receipt on the next calendar day does not. Same-day receipts sort by `recognition_sequence`.

## Remaining gaps

These are raised. They are not given a new rule.

- Decision 7 says the in-duplum clip stays off until counsel names three section 103(5) edges. `duplum.py` still applies a cumulative clip. `IN_DUPLUM_CLIP_POSTS` is false so a posting must not treat that clip as on. The arithmetic module was not rewritten.
- Decision 8 orders due fee buckets as collection costs, default administration, credit insurance, service fee, then initiation, earliest due date first inside a bucket. `allocation.py` still shares a same-day short payment in proportion. It was not rewritten.
- Decision 17 requires half-up everywhere and also says rounding must not create a compliance breach. Opening-month service fee still floors 14/31 of R60 to 2709 cents. Half-up of the unrounded 2709.68 cents is 2710. Which sentence wins for a statutory maximum is not chosen.
- Decision 1 says the system recognition date is the value date, and also that a loan, settlement, or deposit concluded on a calendar day is 00:00 that day. It does not say which wins when the system recognises the event on a later calendar day. `value_date` uses the Johannesburg calendar date of the recognised instant. It does not backdate.
- The campaign discount falls away on the flag date, and a flag-date payment is visible to the morning check. The lock does not say whether the discount is removed before that test or only if the test flags default.
- Decision 4 gives a cash-deposit branch and an insurance branch for credit life, and also describes Day-1 as deposit-insurance style. The branch is not chosen. The child instrument kind remains `security_deposit`. That name is a label. It does not make the loan secured.
- Decision 4 says the hold reduces only the interest base and that the client may settle when the lay-by is at least the settlement balance. It does not say whether that settlement balance is already net of the hold.
- Decision 17's nominal annual rate takes the number of periods from the caller. The lock does not say whether weekly means 52 or 365/7.
- Decision 16 freezes the service address and does not define its shape. The agreement table is still owned by servicing and is not created here.
- Decision 13 allows a restructure to set a new instalment, price, and term. It does not say whether that is a new agreement or an amendment of the frozen pin.
- `keep_instalment` may write off a small residual at contractual end. The lock does not name the sub-ledger.
- Option B of the repo-rate fall issues a section 104 notice. The notice contents and any trigger date beyond the fall are not specified.
- Decision 2 applies the capitalised-versus-section-126 split to related fee points and does not name them. Charges that cause the default are also unnamed. The in-duplum worked table remains arithmetic, not a posting instruction.
- Decision 9 names R60, R165, and R1 050. Other gazetted rand amounts are not listed. Adding exclusive VAT can push a short-term deferred amount through R8 000. The lock does not say how origination behaves then.
- Decision 10 names `none` as the substantive default. Decision 19 says an unset election fails closed. The column is nullable. Storing the word `none` is the provider's choice. The same tension applies to decision 9's "excluding VAT by default" and `vat_on_rand_maxima`. The seeded interpretation `vat_on_prescribed_cap = cap_is_consumer_maximum` still records the older inclusive reading. The lock wins. That seed row was not rewritten.
- The threshold check is greater than 0 and at most 100. Zero percent is rejected. The lock does not say whether 0 is a valid threshold.
- A zero-cost or CPA lay-by product does not inherit a campaign rate, and it may omit a day-count divisor. A credit product may not. The lock does not say a zero-price product needs a divisor, so one was not required.
- `repo_rate_fall` is required when settings are resolved, including for a monthly short-term product whose cap is not repo-linked. Decision 19 lists the election. It does not limit the requirement to a later annual accrual.

## Tests

`python3 -m pytest tests -q` on 28 October 2026: 43 passed.

Covered: unset elections fail closed; a product override wins and a null product inherits; a zero campaign rate is accepted; negative leniency and a threshold outside the stored range are rejected; a missing cap, confirmed repo rate, or tariff row fails the posting that needs it; the audit hash chain links and the next organisation sees no rows; a flag-date receipt is visible to the morning check and same-day receipts keep recognition order.
