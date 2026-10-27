# Account, balance and transaction model

Ledger and account structures for the Day-1 LMS. The source of truth for behaviour is [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) (last updated 2026-10-27). This file records how those locks sit on the data. It does not add, soften, or reinterpret a lock.

If a sentence here is not a lock and not a technical gap, it is only a table shape. Technical gaps are section 8. They are unnamed on purpose: the locked file says not to invent a default. The calculation engine and servicing workflows are not implemented.

Money is integer cents (ZAR) once an amount is billed. Sub-cent working storage is allowed only as an unbilled remainder. See T24.

---

## 1. What each locked section does to the ledger

### 1. Value date and day boundary

- An originating event’s `value_date` is the system recognition date.
- The day boundary is 00:00. A loan, settlement or deposit concluded at any time on a calendar day is stored as 00:00 on that `value_date`.
- A reversal’s `value_date` is the value date the system originally recognised on the reversed event. See T1.
- A payment whose `value_date` is the default flag date is an input to the morning default check. See T3.
- The civil timezone that defines “calendar day” and “00:00” is not named. See T29.
- Several events on one value date are all 00:00. No order among them is locked. See T2.

`recognised_at` is stored as the commit timestamp. It is not an allocation key, except that the originating event’s `value_date` is derived from it.

### 2. Initiation fee

| `initiation_treatment` | Effect |
| --- | --- |
| `capitalised` | Amount is part of `principal`. It is allocated in the principal tier of section 126. A capitalised amount that was capitalised before the default date is inside the in-duplum ceiling. |
| `separate_fee` | Amount is a due fee. It is allocated in the fees tier of section 126. |

“The same logic applies to related fee points.” Those points are not listed. See T4. No other fee is given this treatment by this design.

### 3. Zero rates, zero fees and campaigns

Store and display the base rate and the campaign discount separately. Charged rate = base rate minus discount, and a campaign may set that result to 0%. The same pattern applies to fees set to R0. A zero rate or a zero fee for the whole term, or for any portion of the term, is valid input. Calculations must not fail on zero.

Campaign fields on a concession row: `base_rate` (x %), `discount` (y %), `valid_from`, `valid_to`. Display is “x % with y % deducted”, not a single substituted rate.

- The discount remains in force through the leniency window.
- The discount ends on the default flag date. From that date the charged rate is the base rate.
- A later cure does not restore the discount.
- Penalty interest may not exceed the contractual interest rate. See T5. This design does not create a rate above the base rate.

Overlapping concessions are not locked. See T35.

### 4. Laybye linked to a loan

- A linked lay-by is a child of a parent loan. The contract treats the pair as one loan. It is not modelled as security that would make the loan secured. See T7.
- A payment instruction can name amounts to the loan and to the lay-by.
- Interest for the pair uses the net balance: loan principal minus lay-by hold. The locked file states this is evidence that the hold is treated as a payment against the loan rather than a separate savings product. The parent and child balances are still stored separately, because payments are allocated across both and consolidation compares the hold with the settlement balance. See T6.
- One monthly service fee, levied on the parent. The child has no service-fee posting.
- The client can consolidate or settle when the lay-by hold is greater than or equal to the settlement balance.
- Credit life pays the loan first. The lay-by covers any shortfall only when a section 124 authority was signed in life. Surplus goes to the estate when the lay-by is treated as a cash deposit. When the lay-by is structured as insurance, treatment follows whether a beneficiary was named. See T8.
- A funeral benefit is paid to the named beneficiary. The loan and the lay-by are unchanged.
- Without a section 124 authority signed in life, death does not apply the lay-by. The lay-by stays with the estate.
- The arrangement is deposit-then-disburse: the client pays for a period, then the loan is disbursed. For Day-1 this is not deposit-taking under the Banks Act. Behaviour of fees and statements during the payment period is not locked. See T9.

### 5. Day count and accrual

The provider chooses `actual_actual` or `thirty_360`. New products are recommended to default to `actual_actual`, with `thirty_360` selectable. Accrual is daily. A 360-day year is not a Day-1 requirement; Actual/360 is not added.

The arithmetic inside each named convention is not locked. See T28. Daily accrual still runs. Leniency does not pause it and does not reduce it.

### 6. Default definition

One definition serves in-duplum and collections reporting.

- `leniency_days` is configurable per customer and counts calendar days, including weekends and public holidays.
- `leniency_days` unset, or `full_payment_threshold_percent` unset, fails closed. Example numbers are not defaults.
- Automatic default is flagged only on `contractual due date + leniency_days`, and only when the amount received for that due date is below the threshold.
- The instalment in the threshold test is the original principal slice plus levied charges that share that due date, including the monthly service fee, a non-capitalised initiation fee, and credit life. See T11.
- Unbilled interest is excluded until it is debited. See T11.
- How much of a section 126 payment counts as “received for that due date” is not locked. See T10.
- Credit life is part of the loan instalment used for affordability.
- The contractual instalment is preferred to stay the same during the term. See also section 13 and T19.
- Interest continues daily on the outstanding balance through leniency. See T6 for the base.

### 7. In-duplum

- Ceiling = unpaid principal, including any pre-default capitalised initiation fee, at the date of the first default in that episode.
- Post-default accruals count as charges even when a statement displays them as capitalised. They are not moved into the principal component by that display. See T13.
- Charges that cause the default do not count toward the cap. Charges that accrue during the episode do.
- A payment during the episode reduces what is owed and does not reset that episode’s counter.
- A cure closes the episode.
- A new default opens a new episode. The new ceiling is the unpaid principal at the start of that default.
- This is not a single lifetime ceiling.
- The three section 103(5) edges not decided by *Nedbank v NCR* [2011] ZASCA 35 remain unsigned. The clip stays off until counsel confirms. This design does not name those edges and does not turn the clip on.

### 8. Payment allocation

Section 126 order only:

1. Due or unpaid interest.
2. Due or unpaid fees or charges.
3. Principal.

No order inside tier 2 is locked. See T14. A capitalised initiation fee is principal (tier 3). A non-capitalised initiation fee is a fee (tier 2).

### 9. Service fee pro-rata and VAT

- Pro-rata applies only in the opening month, described as disbursement to first payment due.
- The stated fraction is inclusive days in the month / actual days in that month. See T15.
- After the opening month the fee is the full monthly fee, including in the settlement month, subject to the R60 cap.
- Settlement inside the opening month is not separately stated. See T16.
- Rand maxima R60, R165 and R1 050 are excluding VAT by default (NCR January 2019 note). The provider may elect inclusive. See T17.

### 10. Interest on a deferred initiation fee

Provider choice, stored per organisation or per product.

- Default: no interest on a deferred initiation fee.
- Alternative: interest permitted.

The alternative’s base is not specified. See T18. The default leaves the deferred initiation fee out of the interest base.

### 11. Rate after the repo rate falls

Provider choice, stored per organisation or per product. No platform default. Unset fails closed.

| Stored value | Behaviour |
| --- | --- |
| `contract_rate` | Continue at the contract rate. |
| `lower_of_contract_and_statutory` | Accrue at the lower of the contract rate and the current statutory maximum, and issue the section 104 notice. |

### 12. Statements

One statement per client, listing all of that client’s loans. There is no per-loan statement. Period boundaries are not locked. See T33. Linked lay-bys are part of the parent loan’s picture because the pair is one loan.

### 13. Decision engine, instalments and other fees

- `accept_external_schedules` may be false, which forces the platform engine. The LMS must be able to accept an externally supplied schedule when that is turned on.
- When disbursement is later than the quote date, the stored policy is one of:
  - `recalculate_instalment`: adjust the instalment from the actual disbursement date and the remaining term.
  - `keep_instalment`: keep the original instalment; the loan may settle early, or a small residual may be written off at contractual end. Write-off is not required when the account is already in default. “Small” is not quantified. See T31.
- After a partial prepayment the provider chooses `shorten_term` or `drop_instalment`. See T19.
- The contractual instalment is preferred to stay the same during the term.
- Amounts other than interest, initiation, the monthly service fee and credit life (the locked example is certain collection costs) are added as a further monthly fee, fixed or variable. They are not capitalised into the amortisation schedule. See T21.
- Restructuring creates a new instalment, pricing and term when other costs must be added during the term.
- A subsequent short-term loan is counted per credit-provider organisation. See T20.

### 14. Payment frequencies

`weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual`. The rule that turns an anchor day into the next date, including month-end, is not locked. See T34.

### 15. Enigma

The LMS stores opaque `person_id` and `organisation_id` only, plus the frozen identity fields in section 16. It does not keep a person or organisation registry. Timeout or an ambiguous Enigma status fails closed. See T22.

### 16. Identity freeze

At booking, store the name, ID number and service address returned for that person. Later Enigma changes do not update those three fields on the concluded agreement. See T23.

### 17. Rounding

Billing rounds half-up to the cent. The same rounding rule is used wherever rounding is required. The annual equivalent rate is disclosed. Rounding must not create a compliance breach. The locked example is an instalment rounded up above the affordability figure already aligned with the client. See T24, T25 and T26.

### 18. Default-administration and collection tariffs

No default-administration charge and no collection cost is posted unless a tariff row exists for that value date. Allowable extra costs are added as an additional monthly fee rather than capitalised into the schedule. See T21.

---

## 2. Tables

Aurora PostgreSQL. Amounts that have been billed are `bigint` cents. `ppm` is parts per million (5% = 50000) so a zero rate is a normal zero. Every financial row carries `credit_provider_organisation_id`. Child foreign keys include it. Row-level security uses that id.

Append-only: `agreement_version`, `pricing_concession`, `schedule_version`, `schedule_line`, `ledger_transaction`, `ledger_entry`, `accrual_decision`, `default_episode`, `default_episode_event`, `identity_freeze`, `section_124_authority`. Mutable caches are marked.

### 2.1 `customer_default_terms`

Per customer, as locked. Key: `(credit_provider_organisation_id, consumer_person_id)`.

| Column | Notes |
| --- | --- |
| `leniency_days` | integer, null fails closed. Calendar days. Not defaulted |
| `full_payment_threshold_percent` | numeric, null fails closed. Not defaulted |

### 2.2 `provider_election`

Key: `(credit_provider_organisation_id, product_code null, effective_from)`. A null `product_code` is the organisation row. A product row overrides it where the lock allows organisation or product storage (sections 10 and 11).

| Column | Notes |
| --- | --- |
| `day_count` | `actual_actual` or `thirty_360`. Recommendation recorded for new products: `actual_actual` |
| `interest_on_deferred_initiation` | boolean. Default false. True selects the permitted alternative |
| `repo_rate_policy` | `contract_rate` or `lower_of_contract_and_statutory`. Null fails closed |
| `vat_on_maxima` | `exclusive` (default) or `inclusive` |
| `prepayment_schedule_policy` | `shorten_term` or `drop_instalment`. Null stays null. See T19 |
| `disbursement_adjustment` | `recalculate_instalment` or `keep_instalment` |
| `accept_external_schedules` | boolean. False forces the platform engine |
| `calendar_zone` | text, null fails closed. See T29. Not a locked geography |

### 2.3 `statutory_parameter` and `tariff_row`

Parameter rows hold cited caps (interest, initiation, service fee, short-term thresholds, VAT rate when inclusive is elected). `citation` is required. A missing tariff row for default administration or collection costs fails the post. No rand amount is compiled into the service.

### 2.4 `loan_account`

| Column | Notes |
| --- | --- |
| `id` | uuid |
| `credit_provider_organisation_id` | Enigma organisation. The subsequent-loan count is per this id |
| `consumer_person_id` | Enigma person |
| `status` | Cache of `account_event`: `pending`, `active`, `settled`, `written_off`, `cancelled` |
| `currency` | `ZAR` |
| `opened_on` | Disbursement value date, null while only the deposit period has occurred |

No balance columns. The pair is one loan: there is no secured-loan kind.

### 2.5 `laybye_account`

| Column | Notes |
| --- | --- |
| `parent_loan_account_id` | Required for a linked lay-by |
| `structure` | `cash_deposit` or `insurance` |
| `closed_on` | null while open |

One open linked lay-by per parent. Unique index on `(organisation, parent)` where `closed_on` is null.

### 2.6 `section_124_authority`

| Column | Notes |
| --- | --- |
| `laybye_account_id` | |
| `signed_in_life` | boolean. Death may apply the lay-by only when this is true |
| `evidence_ref` | Opaque reference. What counts as signed is not defined. See T27 |

### 2.7 `identity_freeze`

One row per agreement version, written at booking and never updated.

| Column | Notes |
| --- | --- |
| `full_name` | text |
| `id_number` | text |
| `service_address` | text |

Missing source values: see T23. These three fields are a snapshot, not an identity service.

### 2.8 `agreement_version`

Immutable terms. Holds `quote_date`, `nominal` base rate ppm, `rate_basis` (`annual` or `monthly`), `initiation_treatment`, `initiation_fee_cents`, `service_fee_cents`, `payment_frequency`, `first_due_on`, `contractual_end`, `schedule_origin` (`platform_engine` or `external_engine`), `disbursement_adjustment`, `product_enrolment_id`, `quotation_ref`, and the elections copied from `provider_election` at booking. `annual_equivalent_rate_ppm` is the disclosed figure. See T26.

### 2.9 `pricing_concession`

`kind` `interest` or `fee`, `base_ppm` or `base_cents`, `discount_ppm` or `discount_cents`, `valid_from`, `valid_to`, `campaign_code`. Charged value is base minus discount, floored at zero only in the sense that a campaign may state a discount that brings the result to zero. A discount larger than the base is not given a rule. See T35.

The concession stays effective through leniency. It is not effective on or after the flag date of an episode. A closed episode does not reactivate it.

### 2.10 `schedule_version` and `schedule_line`

A version records `origin`, `adjustment` (`none`, `recalculate_instalment`, `keep_instalment`, `shorten_term`, `drop_instalment`, `restructure`), `frequency`, and `principal_assumption_cents`.

A line has `due_on`, `principal_slice_cents`, `service_fee_cents`, `initiation_fee_cents`, `credit_life_cents`, `other_monthly_fee_cents`. Interest on a line, if present, is an estimate. `other_monthly_fee_cents` is the further monthly fee from locks 13 and 18. It is not added into `principal_slice_cents`.

Creating a line posts nothing. Due-date generation beyond the six frequency names is T34.

### 2.11 `ledger_transaction` and `ledger_entry`

```text
ledger_transaction
  id, organisation_id
  loan_account_id null
  laybye_account_id null
  kind
  value_date          -- originating event: recognition date; reversal: original value date
  recognised_at       -- commit timestamp, not the allocation key
  reversal_of null
  idempotency_key
  correlation_id
  mandate_ref null
  external_ref null

ledger_entry
  transaction_id, organisation_id
  component, direction, amount_cents > 0
```

`kind`: `disbursement`, `initiation_fee`, `interest_debit`, `service_fee_debit`, `credit_life_debit`, `other_monthly_fee_debit`, `default_admin_debit`, `collection_cost_debit`, `payment`, `laybye_receipt`, `laybye_refund`, `consolidate_settle`, `insurance_proceeds`, `funeral_payout`, `settlement`, `residual_write_off`, `reversal`.

Loan receivable components, matching section 101 and the locks: `principal`, `interest`, `initiation_fee`, `service_fee`, `credit_life`, `other_monthly_fee`, `default_admin`, `collection_cost`. `credit_life` is the section 101(1)(e) cost. `other_monthly_fee` is the locked further monthly fee and is not capitalised into principal. Whether `default_admin` and `collection_cost` are also represented only as `other_monthly_fee` is T21. Until that is answered, both component names exist and nothing is posted to `default_admin` or `collection_cost` without a tariff row, and nothing is posted into `principal` from those charges.

Lay-by component: `consumer_funds_held` (liability). Loan liability: `unapplied_credit`.

A transaction balances. A `service_fee_debit` on a lay-by is rejected.

### 2.12 `accrual_decision`

One row per loan per `value_date`. Columns: `net_principal_cents`, `gross_principal_cents`, `base_ppm`, `discount_ppm`, `charged_ppm`, `day_count`, `computed_unbilled`, `duplum_policy`. While the clip is unsigned, `duplum_policy = unsigned` and the decision does not reduce the computed amount. `computed_unbilled` may be sub-cent. Billing posts cents under lock 17. See T24 and T28.

### 2.13 `default_episode`

Opened only by the section 6 test. Columns: `flag_date`, `due_date`, `leniency_days` (copied), `threshold_percent` (copied), `principal_ceiling_cents`, `gross_counter_cents` (cache, unused for clipping while policy is unsigned). Close is a `default_episode_event` of kind `cured`. The ceiling column is the locked formula, stored for the day the clip is allowed. It does not clip while unsigned.

### 2.14 `payment_instruction` and `payment_leg`

An instruction has an amount, a `value_date` at 00:00 on the recognition date, and optional legs. A leg is either the loan or the lay-by, with an amount. Legs may cover both. The sum of legs equals the instruction. No legs, and exactly one open loan for that client, is the loan. No legs and any other number of open loans fails closed rather than by a split rule (no split rule is locked). See T2 for ordering against other same-day events.

### 2.15 `client_statement`

Unique on `(organisation_id, consumer_person_id, period_from, period_to)`. Lines are the client’s loans (and the linked lay-by balances of those loans). No table is keyed as one statement per loan. See T33.

### 2.16 `balance_snapshot`

Cache of component sums. Not a source of truth. Stale when a later-recognised transaction has a `value_date` on or before the snapshot date, which includes a reversal that reuses an earlier value date.

---

## 3. Balances the locks define

```text
principal            includes a capitalised initiation fee
initiation_fee       only when treatment is separate_fee
net_balance          loan principal − laybye hold          (interest base named in lock 4)
customer_owes        sum of loan receivable components − unapplied_credit
settlement_balance   the figure compared with the lay-by hold for consolidate/settle
```

`settlement_balance` is the amount the client must pay to settle. Lock 4 uses it as the consolidate threshold and does not restate its addends. Section 125 of the Act is the statutory composition (unpaid principal, unpaid interest and other fees and charges payable up to the settlement date, and an early-termination charge only on a large agreement). This design does not add a second composition. The opening-month and settlement-month service-fee locks in section 9 are inputs to “fees payable”. See T15 and T16.

Arrears for collections use the same default flag as in-duplum (lock 6). There is no arrears component in the ledger.

The in-duplum ceiling is unpaid principal at the first default in the episode, including pre-default capitalised initiation. It is not reduced by the lay-by hold. The hold reduces the net balance on which interest is calculated. Those are different locked quantities.

---

## 4. Payment when a lay-by is linked

This is the locked order, not a worked example with invented cents.

1. A lay-by leg increases `consumer_funds_held`. It does not post section 126 tiers on the loan.
2. A loan leg allocates in section 126 order: due or unpaid interest, then due or unpaid fees, then principal.
3. `consolidate_settle` is available when `consumer_funds_held >= settlement_balance`. It applies the hold to the loan through that same section 126 order.
4. Credit-life proceeds pay the loan first, through section 126, up to the settlement balance. The lay-by is applied to a shortfall only when `section_124_authority.signed_in_life` is true. If the lay-by is a `cash_deposit`, surplus after that application goes to the estate. If it is `insurance`, the destination follows whether a beneficiary was named (T8). If `signed_in_life` is false, the lay-by is not applied and stays with the estate.
5. A funeral payout pays the named beneficiary and posts nothing to the loan or the lay-by.

Same-day ordering against the daily accrual is T2. The threshold test’s use of “amount received for that due date” is T10.

---

## 5. Invariants

These restate locks. A post that would break one rolls back.

1. An originating transaction’s `value_date` is its system recognition date, stored at 00:00 of that calendar day.
2. A reversal’s `value_date` equals the original transaction’s `value_date`, and the original row remains.
3. `leniency_days` and `full_payment_threshold_percent` are null or set. A default test with either null fails. No code constant is substituted.
4. A default episode opens only on `due_date + leniency_days` calendar days, and only when the received amount for that due date is below the threshold. Leniency days include weekends and public holidays.
5. The discount on a concession is still applied on every value date from `valid_from` through the leniency window, and is not applied on or after the episode `flag_date`. Cure does not turn it back on.
6. Charged interest after the flag date is the base rate, and no posted interest rate exceeds the contractual rate. See T5 before comparing “contractual” with “base”.
7. `net_balance` used for a daily interest decision is loan principal minus the linked hold, when that is the base selected for the decision. See T6 before using any wider “outstanding balance”.
8. A linked pair posts at most one `service_fee_debit` in a calendar month, and only on the parent.
9. `consolidate_settle` requires `consumer_funds_held >= settlement_balance` immediately before the post.
10. A death event does not reduce `consumer_funds_held` unless `signed_in_life` is true. A funeral payout does not reduce the loan or the hold.
11. The in-duplum clip does not change a posted amount while `duplum_policy = unsigned`.
12. An episode ceiling, once stored, equals unpaid principal at that episode’s first default, including pre-default capitalised initiation, and is not rewritten by later payments.
13. A payment does not decrease `gross_counter_cents` of an open episode.
14. Charges that the default test treats as the cause of the default are stored with `counts_toward_duplum = false`.
15. A cure inserts a close event. A later default inserts a new episode.
16. Loan allocation of a single loan leg pays due or unpaid interest before fees, and fees before principal.
17. A capitalised initiation fee has a zero `initiation_fee` balance and a principal balance that includes it. A separate initiation fee has a zero capitalised-initiation amount.
18. `repo_rate_policy` null fails the accrual. `calendar_zone` null fails value-date derivation.
19. No `default_admin` or `collection_cost` entry exists without a tariff row covering its value date.
20. No `other_monthly_fee`, `default_admin`, or `collection_cost` amount is included in `principal_slice_cents` or posted as a principal debit.
21. A zero charged rate and a zero charged fee do not require a non-zero divisor. The schedule builder’s zero-rate path divides principal by the instalment count only. That divisor is the count, not the rate.
22. Billing cents are half-up. One rounding implementation is used at every billing site.
23. `identity_freeze` is insert-only. Enigma updates do not change it.
24. Enigma timeout or ambiguous status aborts the transaction that needed Enigma.
25. Subsequent short-term counting, when implemented, groups by `credit_provider_organisation_id` only. It does not group across organisations. See T20 before adding consumer or year.
26. Debits equal credits on every transaction. Append-only tables reject update and delete. `(organisation, idempotency_key)` is unique.
27. One statement header per organisation, person and period. It is not unique per loan.

---

## 6. Readings withdrawn from the earlier draft

These were in the previous version of this file and are not locks. They are withdrawn.

| Withdrawn reading | Why it is withdrawn |
| --- | --- |
| Reversal receives the recognition date of the reversal itself | Lock 1: the reversal uses the value date originally recognised |
| Same-day order is recognition timestamp, with accrual last | Lock 1: every event on the day is 00:00. Order is T2 |
| Intra-fee allocation by due date then section 101 listing order | Lock 8 states only the three tiers. T14 |
| US NASD 30/360 and Actual/Actual ISDA formulae | Lock 5 names the conventions and does not give the formulae. T28 |
| Month-end due-date clamp from the anchor | Not locked. T34 |
| Linked lay-by makes the loan `short_term_secured` | Lock 4: the pair is one loan, not security that makes it secured |
| Banks Act custody left open for Day-1 | Lock 4: not deposit-taking for Day-1 purposes |
| Death always applies the lay-by after credit life | Lock 4: not without a section 124 authority signed in life |
| Surplus lay-by always refunded to the estate | Lock 4: estate if cash deposit; insurance follows whether a beneficiary was named |
| Service fee excluded from a mid-month settlement | Lock 9: full monthly fee in the settlement month after the opening month |
| Opening-month pro-rata left unsigned | Lock 9 gives a fraction. Numerator detail remains T15 |
| Residual write-off cap as a product setting | Lock 13 says “small” and does not define it. T31 |
| Interest base silently equal to net principal with no outstanding-balance question | Both phrases are locked. T6 |
| Duplum edge policy left for this file to choose | Lock 7: three edges stay unsigned and the clip stays off |
| Names fetched from Enigma at statement time | Lock 16: freeze name, ID number and service address at booking |

---

## 7. Act constraints already reflected by the locks

The engine still cannot post a consumer charge outside section 101’s list. Section 126’s three tiers are lock 8. The section 103(5) clip stays off (lock 7). Tariff absence fails closed (lock 18). VAT-exclusive maxima are the default (lock 9). Nothing in this section adds a rule on top of those.

---

## 8. Technical gaps

No default is chosen for any of these.

| Id | Gap |
| --- | --- |
| T1 | Lock 1 sets the value date to the system recognition date, and sets a reversal’s value date to the date originally recognised. A reversal committed on a later civil day cannot have both dates. The table stores both `recognised_at` and `value_date`, and copies `value_date` from the original. No further replay rule is added. |
| T2 | Every event on a calendar day is 00:00. The order of two payments, or of a payment and the daily accrual, or of a settlement and that day’s interest, is not locked. |
| T3 | A flag-date payment is visible to the morning default check. The lock does not say whether that check runs before later same-day recognitions that carry that flag date. |
| T4 | “Related fee points” that share the initiation-fee capitalise-or-section-126 treatment are not named. |
| T5 | “Contractual interest rate” in the penalty cap is not defined as the base rate or the discounted rate. The flag-date rule sets the charged rate to the base rate. No higher penalty rate is stored. |
| T6 | Interest is “loan principal minus lay-by hold” (lock 4) and also “the outstanding balance” (lock 6). The daily decision cannot pick a wider base than net principal, and cannot ignore the phrase “outstanding balance”. Accrual waits on a lock update if these differ. |
| T7 | The pair is one loan and is not a secured loan. The NCA category (short-term, unsecured, or other) is not named. |
| T8 | Insurance-structured lay-by proceeds “follow whether a beneficiary was named.” The destination in each of those two cases is not stated. Cash-deposit surplus to the estate is stated and can be posted. |
| T9 | The client pays for a period, then the loan is disbursed. Fees, interest and statements during that period are not locked. Whether the parent row must already exist is not locked. |
| T10 | The default test needs the amount received for a specific due date. Section 126 allocation is by interest, fees and principal, not by due date. No attribution rule is locked. |
| T11 | The threshold instalment lists principal slice, service fee, non-capitalised initiation and credit life. A further sentence excludes unbilled interest until it is debited. Whether debited interest then joins that instalment is not stated. |
| T13 | Post-default accruals count toward the cap even if a statement shows them as capitalised. The statement columns for that display are not specified. The ledger does not move those accruals into `principal`. The three unsigned section 103(5) edges stay unnamed. |
| T14 | No tie-break inside section 126’s fee tier. |
| T15 | The opening-month numerator is “inclusive days in the month”, in a sentence that also says “disbursement to first payment due”. The day count to use is not pinned down. |
| T16 | A settlement that falls inside the opening month matches both the opening-month pro-rata rule and the “full fee in the settlement month” rule. |
| T17 | Inclusive VAT has no locked rate, and no locked rule for whether R60, R165 and R1 050 are grossed up or treated as all-in. Exclusive is the default and can be applied to ex-VAT amounts. Inclusive fails closed until a rate row and a comparison rule exist. |
| T18 | When interest on a deferred initiation fee is permitted, the lock does not say whether that fee is added to the net-principal base. |
| T19 | `shorten_term` and `drop_instalment` have no fail-closed rule and no platform default. “Prefer keeping the contractual instalment” is not recorded here as an automatic choice. |
| T20 | Subsequent short-term loans are counted per credit-provider organisation. Regulation 42 Table A also limits the 3% rate to subsequent loans within a calendar year. The lock does not mention the consumer or the year. The counter is not implemented. |
| T21 | A further monthly fee is fixed or variable and is not capitalised. The lock’s example is certain collection costs. It does not say to collapse `default_admin` and `collection_cost` into that fee or to keep them as their own section 101 components. Both names exist. Posts into the schedule’s principal slice are rejected either way. |
| T22 | Fail closed on Enigma timeout or ambiguous status. The timeout duration and the ambiguous statuses are not defined. |
| T23 | Name, ID number and service address are frozen at booking. The lock does not say whether a missing field aborts booking. |
| T24 | Half-up to cents is on billing. It does not say that each daily accrual is a billing event. Daily sub-cent storage versus a billed cent is unresolved. |
| T25 | Half-up must not push an instalment above the affordability figure already aligned with the client. The resolution (block the booking, round down, or something else) is not locked. |
| T26 | The annual equivalent rate must be disclosed. The conversion from the stored base rate is not locked. |
| T27 | “Signed in life” has no evidence standard. The ledger stores a boolean and an opaque reference only. |
| T28 | `actual_actual` and `thirty_360` have no locked day-weight formula. A 360-day year is not required. No formula is coded as if it were standard. |
| T29 | “00:00” and “calendar day” need a timezone. None is locked. `calendar_zone` null fails closed. |
| T31 | “Small” residual is not an amount. `residual_write_off` is not posted. Early settlement from `keep_instalment` does not need that amount. |
| T33 | The client statement has no locked period (calendar month, statement date, or other). |
| T34 | Next due date after an anchor, including a 31st in a short month, is not locked. |
| T35 | Two concessions of the same kind overlapping in dates, and a discount larger than the base, are not locked. |

---

## 9. Out of scope

No calculation engine, no morning-check job, no statement delivery, no origination, no Enigma implementation. The draft checklist of structures and signatures is [ledger-implementation-checklist.md](ledger-implementation-checklist.md). That checklist is a draft. It is not a lock.
