# Account, balance and transaction model

How the ledger stores a loan. The source of truth is [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) (28 October 2026). A sentence below cites the section it follows. It does not add a rule. Gaps are listed at the end and are not given a default.

Money is integer cents once it is billed. A daily accrual is kept as an unbilled decimal until `bill_interest` posts it. Balances are not stored. A bucket balance is the sum of ledger entries with a value date on or before the date asked for.

The executable model is `src/lms/ledger/`. The physical tables are `db/migrations/0004_ledger_accounts.sql`. They describe the same shape. No process yet writes the Python model into PostgreSQL. That join is not this change.

## Tables

| Table | What it holds |
| --- | --- |
| `lms.loan_account` | The loan, or a lay-by hold whose `parent_loan_id` is that loan. `organisation_id` and `person_id` are opaque. Name, identity number, and service address are frozen. |
| `lms.election_snapshot` | The organisation and product elections copied at booking. One row per loan. No nulls, except day count on a zero-price product. |
| `lms.schedule_version`, `lms.schedule_line` | Versions of the principal schedule. A late disbursement records the choice and does not rewrite the amounts. |
| `lms.ledger_transaction`, `lms.ledger_entry` | Append-only double entry. `recognition_sequence` is assigned per organisation. A reversal is a new transaction. |
| `lms.default_episode` | One in-duplum episode. The ceiling is fixed. Closing it is the only later change. |
| `lms.service_fee_levy` | One row per parent loan per calendar month. |
| `lms.client_statement`, `lms.client_statement_balance` | One statement for a person at an organisation for a period, with each loan's own opening and closing bucket amounts. |

Buckets on an entry: `principal`, `interest`, `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`, `laybye_hold`. The hold is credit-normal. The others are debit-normal. `laybye_hold` is not a cost-of-credit balance.

Every financial table carries `organisation_id`. Row level security matches `current_setting('lms.organisation_id')`. The configuration tables use `uuid` for the same identifier. This ledger uses `text`. See the gaps.

## What each locked section does here

### 1. Value date and day boundary

`lms_config.calendar.value_date` is the Johannesburg calendar date of the recognised instant. The ledger stores that date. It does not store a time of day as the value. `value_instant` is 00:00 Africa/Johannesburg on that date.

A reversal copies the original transaction's value date. The recognition time of the correction is stored separately and receives a new sequence. The SQL trigger `lms.enforce_reversal_value_date` rejects any other value date.

Same-day events are ordered by `(value_date, recognition_sequence)`. The sequence is the order the system accepted them, not the clock time inside the day. Receipt ordering calls `lms_config.locked.order_recognised_events`.

A receipt whose value date is on or before the flag date is visible to `is_in_default_at_morning_check`. The ledger does not run a scheduler. A receipt that has not been posted yet is not visible.

### 2. Initiation fee

The frozen `initiation_capitalised` flag decides the posting.

- Capitalised: the fee is debited to `principal`. It is not an initiation-fee charge. The amount is remembered so the in-duplum ceiling can include it. The schedule the caller supplies must already sum to cash advanced plus the fee. The ledger does not spread the fee across instalments.
- Not capitalised: the fee is a due charge in the `initiation` bucket from the disbursement value date, and section 126 allocates it in the fees tier.

Short-term and unsecured templates leave the flag false. The configuration publish check rejects a true flag for every current classification. The ledger posts a true flag when the caller has frozen one. It does not keep a list of section 102 products. Related fee points are not named in the lock, so no other bucket is capitalised.

### 3. Zero rates, zero fees, and campaigns

`base_rate` and `discount_rate` are both stored on the snapshot. The charged rate is `lms_config.locked.campaign_rate`: base minus discount while the discount still applies, and the base rate once `discount_fallen_away` is set. A zero result is posted as zero. A zero service fee is accepted and still occupies the month, so a second fee that month is refused.

The discount stays through leniency, because the flag that removes it is set only when the morning check flags default. It is not cleared when the episode closes.

`campaign_rate` treats the base rate as the contractual ceiling, so the rate after the discount falls away is not above the base. If "contractual interest rate" in this section means the discounted rate, the flag-date rate would exceed it. That reading is not chosen here.

### 4. Lay-by as a child of one loan

`open_laybye` inserts a `laybye_hold` row with `parent_loan_id` set. A second child of the same parent is refused. The pair is not given a security classification. The hold is a credit balance, not a reduction of principal.

Interest uses `lms_config.locked.interest_bearing_cents`. With no capitalised initiation excluded, that is `max(0, principal − hold)`. Principal and `duplum_base_cents` do not subtract the hold.

The monthly service fee is levied only on the parent, once per calendar month of the value date. A levy on the child is refused.

A deposit and a loan receipt are separate postings. One receipt is not split across the loan and the hold. Consolidation when the hold reaches the settlement balance is not implemented. Credit life, funeral, and death are not implemented. `lms.calc.laybye.guard_s124` is not called.

### 5. Day count and accrual

The snapshot's `day_count_code` is `actual_actual` or `thirty_360`, copied by `resolve_customer_settings`. A credit product with neither fails at booking. A zero-price product may omit it.

Daily accrual calls `lms.calc.interest.accrual_weight` and `divisor_days`, then `daily_interest_rands`. The weight for 30/360, including a zero weight on the 31st and the February adjustment, is that function's reading. It is not stated in section 5. Actual/actual uses one weight per calendar day and the actual number of days in the month or year. A 360-day divisor is used only when 30/360 was selected.

The day's result is an unbilled memo. It is not yet allocatable.

### 6. One default test

`flag_default` calls `is_in_default_at_morning_check` with the snapshot's leniency days and threshold. There is no numeric default. Leniency is calendar days because that function adds `timedelta(days=leniency_days)`.

The caller passes `instalment_cents`. The ledger does not build "principal slice plus levied charges that share that due date". Whether debited interest joins that figure is not locked.

An unattributed receipt fails the check. Section 126 does not say which due date a receipt belongs to, and this section needs that amount.

Interest for a day in the leniency window is still accrued. The accrual does not look at the default flag to reduce the base.

### 7. In-duplum episodes

The ceiling is `duplum_base_cents(principal − capitalised initiation, capitalised initiation)`, which is the gross unpaid principal, including pre-default capitalised initiation, and not the hold. It is stored on the episode and not revised.

A charge debited while an episode is already open increases `accrued_cents` by the full cents. A payment does not reduce the counter. A cure sets `closed_on`. The next default opens a new episode and a new ceiling from the principal at that time.

`clip_in_duplum` raises while `IN_DUPLUM_CLIP_POSTS` is false. The ledger does not call `lms_config.duplum.post_month`. An accrual or levy above the ceiling is posted in full.

Charges posted before the episode opens are not added to the counter. The lock says charges that cause the default do not count. Which of those charges "caused" it is not named, so the ledger uses the episode boundary instead of a list.

### 8. Payment allocation

`post_payment` builds a calculator `State` from billed charges and principal slices, then calls `lms.calc.allocation.allocate_payment`. Unbilled accrual memos are not in that state.

The calculator's order is due interest, then collection costs, default administration, credit insurance, service fee, initiation fee, earliest due date first inside a bucket, then due principal. Principal that is not yet due uses the prepayment choice below.

`lms_config.allocation` still splits a same-day short payment in proportion. The ledger does not call it.

The further monthly fee is not in that order. If a receipt could not pay every named fee and that further fee, the posting is refused. If it can pay all of them, both are cleared and the order does not matter. Inside the further-fee bucket alone, the earliest due date is paid first, which is the within-bucket sentence of this section.

A receipt larger than the due amounts and the chosen prepayment has no locked home and is refused.

### 9. Service fee and VAT

The opening month calls `lms.calc.fees.opening_service_fraction` and `service_fee_cents`. Later months ask for a full month. The monthly amount is the caller's figure, and the calculator rejects a figure above R60. Rand caps are not typed into the ledger.

The VAT election on the snapshot is `exclusive` or `inclusive`. A missing election fails at booking. Section 9 names exclusive as the default and section 19 says an unset election fails closed. The ledger follows section 19: null is not written as exclusive. The VAT rate is an argument. None is assumed.

The opening fraction is not shortened when the loan settles inside the opening month. This section does not say to stop the numerator on the settlement date.

### 10. Interest on a deferred initiation fee

The snapshot stores `none` or `permitted`. `interest_bearing_cents` removes the capitalised initiation from the interest base when the value is `none`, and leaves it inside the base when the value is `permitted`. Section 10 names "no interest" as the substantive default. Section 19 says an unset value fails closed. Null does not become `none`.

When the fee is excluded from the base and a principal receipt would have to choose whether it reduces that fee or the cash principal, the receipt is refused. That choice changes the later interest base, and this section does not make it.

### 11. Repo-rate fall

An unsecured accrual calls `lms.calc.interest.personal_annual_rate` with the snapshot's choice mapped to `contract_rate_continues` or `lower_of_contract_and_cap`. A missing choice fails at booking. No section 104 notice is produced. A campaign discount on an unsecured rate is refused, because this file and section 3 do not say whether the discount comes off the margin or off repo-plus-margin.

### 12. Statements

`issue_statement` records one period for one person at one organisation and returns every loan of that person at that organisation, including a lay-by child, each with its own opening and closing principal, interest, and hold. A second period that overlaps the first is refused. The lock does not define the period. The overlap refusal is only so the same day is not on two statements. It is not a locked cycle.

Figures are read from the ledger at request time. A reversal keeps the original value date, so it restates that period rather than the day the correction was recognised.

### 13. Late disbursement, prepayment, and other fees

Late disbursement and partial prepayment are read from the snapshot. Either missing fails at booking, through `resolve_customer_settings`.

If the disbursement value date is after the quoted date, the schedule version records `adjust_instalment` or `keep_instalment` and keeps the caller's lines. The new instalment is not calculated. A residual write-off is not posted. "Small" is not defined.

A receipt that reduces principal which is not yet due calls `allocate_payment` with `shorten_term` or `drop_instalment`. The calculator reduces the latest unpaid slice, or the earliest. That direction is the calculator's, and section 13 does not state it. Due principal does not need the choice.

`additional_monthly` is debited to its own bucket. It is not added to principal or to a schedule line.

A restructure that sets a new price and term is not implemented. A subsequent short-term count is not implemented. Section 13 counts it per organisation and per calendar year and does not name the consumer.

### 14. Frequencies

`weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, and `annual` are accepted and stored. `next_due_date` adds 7 or 14 days, or the same day in a later month. If that day does not exist in the target month, it raises `due-date-unspecified`. The lock does not say to clamp it.

### 15. Enigma

The ledger stores `organisation_id` and `person_id` and does not call Enigma. A timeout, an ambiguous status, or a suspended enrolment is not classified here. There is no client and no session middleware.

### 16. Identity freeze

Booking requires a name, an identity number, and a service address. Those fields cannot be assigned again on the Python account, and the SQL trigger rejects an update. The lock does not say what a missing field does. A blank value is refused so a freeze row is not stored empty.

The lay-by child freezes the identity the caller presents at the child's booking. It copies the parent's election snapshot rather than resolving the organisation again, so a later settings change does not split the pair. The lock does not say which of those two a later child booking should do.

### 17. Rounding and disclosure

`bill_interest` posts `lms.calc.money.to_cents` of the sum of unbilled accrual memos, which is half-up to the cent, once for the sum rather than once per day. A second bill with no new accrual posts nothing. Service fees are rounded by `service_fee_cents`, which uses the same half-up.

No comparison is made with an affordability figure. This section says rounding must not create a compliance breach and does not say whether to block or to round down. The ledger does not have the affordability figure.

`nominal_annual` calls `lms_config.locked.nominal_annual_rate`: periodic rate times the periods the caller supplies. The lock does not say whether weekly means 52 or 365/7.

### 18. Tariffs

A default-administration or collection-cost levy calls `require_reference_for_posting` with `tariff_required` true. A missing tariff row fails. The ledger does not invent a tariff. An allowed extra cost posted as `additional_monthly` is not capitalised. The same configuration function also requires the caller to say an interest cap is present, including on a tariff posting. The ledger does not split that check.

### 19. Where elections live

`resolve_customer_settings` applies a product override when the product value is set, otherwise the organisation value. The result is copied onto `election_snapshot` and not read again. Unset leniency, threshold, initiation-interest choice, repo-rate fall, VAT election, late disbursement, and partial prepayment fail closed. Day count fails closed for a credit product and may be absent for a zero-price product, which is that function's reading of section 5.

## Raised, not solved

These are gaps or conflicts. The ledger does not close them.

1. Section 4 calculates interest on principal minus the hold. Section 6 says interest continues on "the outstanding balance". The ledger uses `interest_bearing_cents`. That phrase in section 6 is wider than the hold adjustment, and it is not read as a second base.
2. Section 3's contractual ceiling may mean the discounted rate. `campaign_rate` uses the base rate. See section 3 above.
3. Section 5 requires 30/360 and also says a 360-day year is not required. The weight inside 30/360 is the calculator's. The configuration note says the same.
4. The calculator's own note says the in-duplum clip stays on. Section 7 says it stays off. `lms_config.duplum` still contains a clip, and `IN_DUPLUM_CLIP_POSTS` is false. The ledger posts no clip.
5. Section 8's fee order and `lms_config.allocation`'s proportional split disagree. The ledger calls the calculator only.
6. Section 9's exclusive default and section 10's "no interest" default disagree with section 19's fail closed. Null is rejected. The word `none` or `exclusive` has to be stored by the provider.
7. A receipt dated after the flag date is not counted by `is_in_default_at_morning_check`, which only keeps receipts on or before the flag date. The lock does not say a later receipt is ignored. The ledger does not add a second cure rule.
8. Section 1's recognition date and the sentence that a loan concluded on a calendar day is 00:00 that day disagree when the system recognises the event on a later day. `value_date` does not backdate.
9. The threshold instalment is not assembled. Debited interest's place in it is open. Due-date attribution of a section 126 receipt is open, so an unattributed receipt fails.
10. The further monthly fee has no rank among the section 8 buckets. A short payment that would choose is refused. Whether default administration and collection costs are that further fee or separate buckets is open. Both exist, and neither is capitalised.
11. VAT inside the in-duplum counter, the three unnamed section 103(5) edges, and whether an unbilled memo counts before it is debited are open. The counter tracks debited cents after the episode has opened. The clip is off, so the counter does not change the amount posted.
12. Reducing capitalised initiation when it earns no interest is refused while both portions are still positive. The permitted case does not change the interest base, because both portions are inside it.
13. An unsecured campaign discount is refused. A discount larger than the base is rejected by `campaign_rate`. The calculator floors that case at zero. The ledger uses the configuration function.
14. Late-disbursement arithmetic, the "small" residual, and a restructure's new price are not implemented. No residual write-off is posted.
15. The subsequent-loan consumer is not named. No count is kept.
16. A due date that does not exist in the target month is refused. No clamp is applied.
17. Blank identity is refused. The shape of the service address is not locked.
18. Half-up against an affordability figure is not compared. Half-up against a statutory maximum is not reconciled: the calculator half-ups an opening service fee, and the configuration helper floors one. The ledger calls the calculator.
19. The number of periods in a year for weekly, fortnightly, quarterly, and bi-annual disclosure is not locked. The caller passes it.
20. Splitting one receipt across the loan and the lay-by, the settlement comparison, credit life, funeral, and death are not implemented. The insurance payee when a beneficiary was or was not named is open. A cash-deposit surplus to the estate is locked and has no posting path yet.
21. Fees during a deposit that is taken before the loan is disbursed are not defined. A lay-by can be opened only after the parent loan exists.
22. Statement period bounds are not locked. Overlap is refused. That refusal is not a locked calendar.
23. Opening-month settlement does not change the locked numerator.
24. Same-day interest uses the principal left by earlier sequences that day. The calculator's note says the day's interest uses the principal from before the receipt. Section 1 orders events by recognition sequence. The ledger follows the sequence.
25. `require_reference_for_posting` requires an interest-cap flag even for a tariff posting. The ledger does not weaken that function.
26. Reversing a default flag is undefined. Reversing a receipt does not re-run the morning check.
27. The configuration organisation id is `uuid`. The ledger stores opaque text. There is no shared foreign key.
28. The Python ledger and the SQL tables are not connected by a repository. Doing that inside a request needs the session that sets `lms.organisation_id`. That session middleware is out of scope, as is the Enigma client.
