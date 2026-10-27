# LMS configuration, reference data, and audit

`docs/LOCKED_DECISIONS.md` is the source of truth for calculation, ledger, servicing, and configuration behaviour. This document is the storage and the read path. Where the two differ, the locked decisions win. Do not invent a default for a choice that document leaves open.

The LMS prices and services agreements. Enigma owns who the parties are. This document is the storage and the read path for the three things the LMS still owns: configuration, statutory reference data, and the financial and operational audit log.

The ceiling arithmetic lives in `src/lms_config`. The tables live in `db/migrations/0001_lms_owned.sql` and `db/seed/001_reference.sql`. Tests lock the worked examples below to that code.

## Boundary

Enigma (`eugene-ehlers/enigma`) owns identity, organisations, memberships, product enrolment, roles, and mandates. This schema does not create those tables and has no foreign key to them. The private repository was not readable from this environment, so `organisation_id` and every Enigma person, actor, and mandate id are opaque UUIDs. If Enigma issues a different id type, that is a column-type change and nothing else.

What the LMS stores against an organisation id:

| Owns | Does not own |
| --- | --- |
| Product parameters, fee and interest rules, white-label presentation, feature flags | Whether the organisation may offer the product (enrolment) |
| NCA caps, day-count conventions, thresholds, public holidays, the repurchase rate | The organisation's legal name and NCR registration number |
| Financial postings and LMS operational changes | Person, membership, role, and mandate changes |
| VAT-vendor flag, as a calculation input | A second copy of the organisation |

The NCR registration number is read from Enigma when the agreement is originated and copied onto the agreement pin. Statements print the pin. They do not join Enigma, and configuration has nowhere to type a competing number.

A feature flag gates a feature. It is not a price. A brand changes a document. The calculation engine reads neither.

## What an agreement pins

The servicing agreement table is not in this migration. Origination writes a pin, and every later accrual reads it:

| Field | Source | Changes later? |
| --- | --- | --- |
| `organisation_id`, `enigma_person_id` | Enigma | No |
| `terms_version_id` | Published `cfg_product_terms.id` | No. A new version does not reprice this agreement |
| `classification` | The terms at origination | No. A zero-cost plan is not silently reclassified when someone wants a late fee |
| Contractual rate as base rate minus campaign discount | The terms. The performing rate is base minus discount, and may be zero. On default the discount falls away and the rate is the base. Penalty interest is that rate, so it does not exceed the contract | The base and the discount are pinned. A later campaign does not reprice this agreement |
| `leniency_days`, `full_payment_threshold_percent` | Organisation, unless the product overrides it. Copied onto the agreement. Null at both levels fails closed. The examples 4, 5, and 95 are not defaults | No |
| `interest_on_deferred_initiation` | Organisation, product override. Locked default is `none` | No |
| `repo_rate_fall` | Organisation, product override. No platform default | No |
| `day_count` | The terms. Locked decision 5: `actual_actual` (recommended for a new product) or `thirty_360` | No |
| `short_term_ordinal` | Count of prior disbursed short-term agreements for this organisation and person | No |
| `ncr_registration_number` | Enigma, copied at origination | No |

The statutory ceiling is not pinned. On each accrual date the engine reads the cap in force that day. A short-term monthly cap is applied on every accrual, because it is the cap for that loan's ordinal. For a repo-linked rate, locked decision 11 is a provider choice stored as `repo_rate_fall`: `contract_rate` keeps the contract rate when the repo falls, and `lower_of_contract_and_cap` accrues at the lower figure and the section 104 notice is issued. Null fails closed. Section 104 still forbids a unilateral increase, so a later rise in the cap does not raise a fixed contract. A rate above the cap on the origination date is refused, including a campaign base that would apply only after the discount falls away.

Sub-ledgers the future ledger has to keep, because section 126 and section 103(5) need them separate even after regulation 40 adds interest to the deferred amount:

`principal`, `interest`, `initiation_fee`, `service_fee`, `default_admin`, `collection`, `credit_insurance`, `deposit`, `layby_penalty`, `early_termination`.

The interest base for the next day is the sum of the sub-ledgers the agreement says interest runs on, minus a linked lay-by hold, and minus a deferred initiation fee unless the provider chose to charge interest on it. A capitalised initiation fee is part of `principal` (locked decisions 2 and 7). Post-default interest and fees stay in their own sub-ledgers even when a statement shows them as capitalised.

## How the engine reads configuration

One `REPEATABLE READ` transaction. No call to Enigma. If a required row is missing, the posting fails. A missing fee means zero, never "use the cap".

1. **Agreement pin**, including the terms version id and the short-term ordinal.
2. **`cfg_product_terms` by primary key.** Not "whatever is current".
3. **`cfg_fee_rule` and `cfg_instrument` for that version.**
4. **`ref_interest_cap`** whose span covers the Johannesburg business date, for the pin's classification.
5. **`ref_initiation_fee_cap`**, **`ref_service_fee_cap`**, **`ref_charge_rule`**, **`ref_threshold`** the same way, when the posting is a fee, a size test, or a short-term limit.
6. **`ref_reference_rate`** code `SARB_REPO`, `confidence = 'confirmed'`, covering that date. A variable rate, and any `RR + margin` cap, fails closed without it.
7. **`ref_interpretation_set`** with status `adopted` covering that date, and its choices. The set id is written on the audit row.
8. **`cfg_organisation_settings.vat_vendor`** for that organisation, and only because the VAT split needs it.
9. **Post the ledger and the audit rows in the same transaction.** If the audit insert fails, the ledger rolls back.

Business dates are `Africa/Johannesburg`. `2026-10-31 22:30 UTC` is `2026-11-01` in Johannesburg. Day-1 organisation settings reject any other zone, so a tenant cannot move a due date across a cap change by picking a timezone. South Africa does not observe daylight saving; the zone is still named rather than hard-coded as UTC+2.

`cfg_cache_generation` increments when terms or flags change. Caps and holidays may be cached against that generation. A terms version is not cached past the request that pinned it.

The SQL for steps 2, 4, and 6, and the ordinal query the servicing table must answer, are in `src/lms_config/context.py`.

### Rate the engine then uses

Short-term and incidental caps are monthly rates. They are not converted to an annual rate for the cap test. Regulation 42 requires those two to be disclosed as a monthly rate. Five percent a month is the cap, not "60 percent a year" and not the compounded equivalent.

Unsecured and the other Table A annual rows are `repo + margin`. On 26 October 2026 the confirmed repo rate is 7.25 percent (MPC statement of 23 September 2026, effective 25 September). The unsecured ceiling is 28.25 percent a year.

```text
performing = base_rate - discount_rate
rate       = base_rate            if in default, else performing
chargeable = rate                 if repo_rate_fall = contract_rate and the accrual is after origination
           = min(rate, statutory) if the cap is a short-term monthly cap, or repo_rate_fall = lower_of_contract_and_cap
```

### A payment, in order

1. Resolve the business date and the rows above.
2. Interest since the last posting is the sum of the unrounded daily amounts. Each day uses that day's interest-bearing balance. Locked decision 1 value-dates a loan, settlement, or deposit at 00:00 on its Johannesburg calendar day, so a payment received today reduces today's base. Leniency does not remove a day from this sum.
3. Half-up the sum to the cent, then clamp it to the in-duplum room and to the rate ceiling. Regulation 40(4) allows 0.1 percent a year against the prescribed daily sum; a half-cent is inside that. A cap itself rounds down, so the consumer is not charged a cent over the gazetted figure.
4. If today is the capitalisation day, post that interest to the interest sub-ledger. Regulation 40 adds interest at most once a month. It is payable from then. Section 103(3) forbids debiting a day's interest before the end of that day.
5. Fees that fall due today are posted the same way, clamped to whatever room remains.
6. Section 126(3) allocates the payment: payable interest, then payable fees, then principal. Current-month interest that has not reached its capitalisation date is not in the interest tier. A section 125 settlement is different and does include interest up to the settlement date; the settlement path posts that accrual before it allocates.
7. One financial audit row per slice, sharing a `correlation_id`.

### Origination, which is not an accrual

Enigma must say the organisation is enrolled for the product. The LMS then loads the latest published terms with `effective_from <= business date` (`cfg_product_terms_current`). `validate_terms` rejects a version that cannot be published. The short-term ordinal is:

```sql
SELECT count(*) + 1
FROM servicing.agreement
WHERE organisation_id = :organisation_id
  AND enigma_person_id = :enigma_person_id
  AND regulatory_classification = 'short_term'
  AND disbursed_on IS NOT NULL
  AND disbursed_on < :business_date
```

A quote, and a cancellation or rescission before the advance, does not count. The servicing table needs an index on `(organisation_id, enigma_person_id, regulatory_classification, disbursed_on)`. That table is not created here.

Publish order for a terms version: insert the draft, insert fee rules and instruments, then set status to `published`. Published rows cannot be updated. A change is a new version. Fee rows of a published version are frozen, so they have to exist before the status flip.

## Reference data

Global. Not tenant scoped. The application role can read it and cannot write it. A correction is a new effective-dated row. Overlapping spans for the same key are rejected.

| Table | What it holds |
| --- | --- |
| `ref_instrument` | The Act, regulation, or announcement a row was transcribed from |
| `ref_credit_classification` | Table A categories, plus `zero_cost` and `cpa_layby` |
| `ref_interest_cap` | Table A after GN 1080. `repo_plus` or a monthly rate, with the short-term 3 percent subsequent rate beside the 5 percent |
| `ref_initiation_fee_cap` | Table B: flat cents, threshold, 10 percent marginal rate, absolute cap |
| `ref_service_fee_cap` | Regulation 44 monthly maximum. The annual maximum is twelve times this and is not stored again |
| `ref_threshold` | Section 7(1)(b) size thresholds, and the regulation 39 R8 000 / 6 month short-term limits |
| `ref_charge_rule` | The 15 percent initiation limb, the 1 percent lay-by penalty, and the tariff rules that have no rand amount |
| `ref_tariff_amount` | Empty on purpose. Default administration and collection costs cannot post until a tariff row is loaded |
| `ref_reference_rate` | SARB repurchase rate. Only `confidence = 'confirmed'` prices a loan |
| `ref_day_count_convention` | The four regulation 40 choices |
| `ref_public_holiday` | Public Holidays Act dates for 2026–2032, Sunday observance included, plus later presidential rows |
| `ref_allocation_tier` | The three section 126(3) tiers, and no fourth |
| `ref_balance_code` | Sub-ledger, which tier it belongs to, and whether section 103(5) counts it |
| `ref_status_code`, `ref_status_transition` | Servicing vocabulary. Not an NCA schedule |
| `ref_interpretation_set`, `ref_interpretation_choice` | The adopted reading of text the statute does not settle |
| `ref_audit_event_type`, `ref_feature_flag` | Closed vocabularies |

Figures seeded from the texts that were actually read:

| Item | Figure | Source |
| --- | --- | --- |
| Unsecured interest | RR + 21% a year | GN 1080, GG 39379, Table A item 3, effective 6 May 2016 |
| Short-term interest | 5% a month, and 3% a month on a subsequent loan | Table A item 5. Who is subsequent is not defined in the notice |
| Incidental interest | 2% a month | Table A item 7 |
| Other Table A margins | Mortgage RR+12, facility RR+14, developmental RR+27, other RR+17 | Same notice |
| Initiation, short-term and unsecured | R165 + 10% of the amount above R1 000, never above R1 050, and never above 15% of the principal debt | Table B and regulation 43(3) |
| Incidental initiation | Nil | Table B |
| Service fee | R60 a month | Regulation 44 as substituted by GN 1080. Pro rata in the calendar month of conclusion |
| Short-term definition | Deferred amount at inception not above R8 000, repayable within 6 months | Regulation 39(2) |
| Agreement size | Small at or below R15 000, large at or above R250 000 | GN 713, GG 28893, 1 June 2006, section 7(1)(b). Section 9 |
| Lay-by penalty | At most 1% of the full purchase price | CPA section 62 and regulation 34 |
| Repo rate | 7.25% from 25 September 2026 | SARB MPC statement, 23 September 2026 |

Default administration (regulation 46) and collection costs (regulation 47) are tariff references, not rand caps. No tariff was transcribed in this pass. The posting fails closed. That is deliberate.

The 2006 initiation and service-fee figures were replaced on 6 May 2016 and are not seeded. An accrual before that date fails closed. Pre-2016 books are out of scope until those rows are loaded from the 2006 text.

A gazette sweep from 2016 through October 2026 was not completed for every threshold. The 11 May 2016 consolidation still shows R15 000 and R250 000, and the amendment found from that date changes the section 42 registration threshold, not section 7(1)(b). Confirm there is no later amendment before go-live. A later amendment is a new row.

## Configuration

Every configuration row carries `organisation_id` except the child rows of a product, which inherit it through `cfg_product`.

`cfg_organisation_settings` is one row per organisation: Johannesburg timezone, ZAR, locale, and `vat_vendor`. It also stores `leniency_days`, `full_payment_threshold_percent`, `interest_on_deferred_initiation` (default `none`), and `repo_rate_fall` (null until the provider chooses). No legal name, no NCR number. "Customer" in locked decision 6 is this organisation. A product column of the same name overrides it. Null does not mean zero days or 100 percent.

`cfg_brand` is display name, support contacts, logo key, statement footer. Presentation only.

`cfg_feature_flag` is an effective-dated insert. The catalogue is `origination_enabled`, `debit_orders_enabled`, `statements_enabled`, `bnpl_enabled`, `layby_security_enabled`. Overlapping spans for the same flag are rejected.

`cfg_product` is the stable id. `enigma_enrolment_code` is the code Enigma uses. The row does not grant enrolment.

`cfg_product_terms` is the priced version. `rate_kind` is `zero`, `fixed_monthly`, `fixed_annual`, or `variable_rr_plus`, and the check constraint allows only the matching rate column. A credit rate is stored as `base_rate` minus `discount_rate`, and the effective column must equal that difference, including zero. `intraday` is `start_of_day` (locked decision 1). `prorate_settlement_service_fee` cannot be true (locked decision 9). The same row may override the organisation's leniency, full-payment threshold, initiation-interest choice, and repo-fall choice.

`cfg_fee_rule.charge` is `zero`, `fixed`, `statutory_formula`, or `tariff`. Initiation is published as `statutory_formula` so the engine caps each agreement. A fixed initiation amount is rejected at publish, because an amount that is lawful on R8 000 can break the 15 percent limb on a smaller loan. `tariff` is how default administration and collection are represented, and it still cannot post without `ref_tariff_amount`.

`cfg_instrument.kind` is `credit`, `security_deposit`, or `cpa_layby`. A security deposit must set `setoff_requires_mandate`. Set-off without an Enigma mandate id is refused. The deposit is not a CPA lay-by, so the 1 percent penalty is not available on it.

### Day-1 templates

`src/lms_config/templates.py`. A tenant may charge less. Publish runs `validate_terms`.

| Template | Classification | Price | Shape |
| --- | --- | --- | --- |
| Micro / short-term | `short_term` | 5% a month contractual. The engine cuts a later loan to 3% | Actual days in the month. Term at most 6 months. Deferred amount at most R8 000. Initiation by formula. Service fee R60 |
| Unsecured personal | `unsecured` | RR + 21% | Divisor 365. Commercial maximum principal R249 999.99, which is below the large-agreement line on purpose |
| BNPL | `zero_cost` | Nothing | Any positive rate or fee is rejected. A late fee is a new product, classified `incidental` (2% a month, initiation nil), not a flag on this one |
| Lay-by of goods | `cpa_layby` | No interest | Cancellation penalty is the statutory formula, and the engine still returns nil if it was not disclosed or the consumer died or was hospitalised |
| Lay-by as security | `short_term` plus a `security_deposit` | The loan is priced as short-term. The deposit is 0% | No CPA penalty. Set-off requires a mandate id |

Section 102 lets a defined list of agreement types defer an initiation fee after the consumer is offered the chance to pay it upfront and declines. Short-term and unsecured credit are not on that list. Day-1 still defers the fee only after that offer is declined, and refuses to call the agreement short-term if cash plus the fee exceeds R8 000. The largest cash advance that survives that test, with the fee capitalised on the cash-advanced reading, is **R7 213.64**. The fee is **R786.36**. The deferred amount is **R8 000.00**. One cent more cash does not fit. Paying the fee upfront leaves the deferred amount equal to the cash, so the cash can be R8 000 and the fee is a separate payment.

## Audit log

`audit_event` is append-only and partitioned by UTC month from October 2026 through December 2032. The primary key is `(occurred_at, event_id)` because the partition column has to be in the key. A financial event requires `amount_cents` (zero or more). An operational event must not carry one. The seal trigger rejects anything else.

Each row stores `previous_hash` and `row_hash` (SHA-256 over the organisation, event id, previous hash, type, time, amount, balance, and payload). The chain is per organisation, taken under a transaction advisory lock, with the head in `audit_chain_head`. Idempotency cannot be a unique index on the partitioned table without the partition column, so `audit_idempotency` is the unique `(organisation_id, idempotency_key)`.

Actor is `person`, `system`, or `mandate`, with an Enigma id when it is not the system. Payload is a JSON object. It must not contain an identity number, a card number, or a credential. `enigma_person_id` is the reference.

Financial types: interest accrued and suppressed, fee accrued and suppressed, payment received, payment allocated, principal advanced, settlement applied, balance written off, posting reversed, deposit received, deposit released, set-off applied.

Operational types: terms published, organisation settings changed, brand changed, feature flag changed, agreement status changed, statement issued, debit order submitted, reference data published, settlement quoted.

Regulation 55(5) says records are kept for three years from when the registrant created, signed, or received the document. Regulation 56 says section 170 agreement records are kept for three years from termination, or from the application date if credit was refused. The agreement-specific rule is the one that governs payments and charges. Partitions are therefore not dropped three years after the event. A loan that runs for five years still needs its origination rows until three years after it ends. Archive after `terminated_on + 3 years`, per agreement, not by detaching a month.

Indexes: `(organisation_id, occurred_at desc)` for a tenant export, `(agreement_id, occurred_at desc)` for a statement or a dispute, `(organisation_id, correlation_id)` for one business action.

## Access patterns

| Caller | Query | Index |
| --- | --- | --- |
| Accrual | Terms by pinned id | `cfg_product_terms` primary key |
| Accrual | Fees and instruments for that version | Primary key prefix `terms_id` |
| Accrual | Cap, threshold, repo rate covering a date | Primary key `(key, effective_from)` plus the exclusion span, so two rows cannot cover one day |
| Accrual | VAT vendor | `cfg_organisation_settings` primary key |
| Accrual | Append audit | Partition for that UTC month, then the three indexes above |
| Origination | Latest published terms | `cfg_product_terms_current` on `(product_id, effective_from desc) WHERE published` |
| Origination | Short-term ordinal | Servicing agreement index named above. Not this schema |
| Admin | Products for one organisation | Unique `(organisation_id, product_code)` |
| Statement job | Brand | Primary key `(organisation_id, brand_code)`. Never on the accrual path |
| Notice period | Is this date a business day | `ref_public_holiday` primary key. Section 2(5): exclude the start day, skip Saturday, Sunday, and public holidays, include the landing day |
| Retry | Same idempotency key | `audit_idempotency` primary key |

Row level security is forced on the tenant tables. The session variable `lms.organisation_id` is the Enigma organisation for the request. The runtime role is `lms_app`. Reference tables have no tenant column and are readable by that role. The runtime role cannot insert them.

`lms.is_business_day(date)` matches `lms_config.calendar.is_business_day`. Section 2(5) counting lives in Python (`add_business_days`). The two have to move together; the October 2026 and August 2026 examples below are the regression cases.

## Readings that are not settled

The seed's interpretation set `day1-adopted` records each one. `locked` means `docs/LOCKED_DECISIONS.md` has closed the question. `safe_ceiling` means the adopted option charges less than or equal to the alternative, so a later decision that the alternative was right leaves the consumer over-charged by nothing. `either_way` is where the engine can be on the expensive side of another plausible reading. Counsel should start there.

Locked, and no longer open in this engine:

- Day boundary is 00:00 on the Johannesburg calendar day (decision 1).
- Default, for in duplum and for collections, is the contractual due date plus the configured leniency, and only if receipts are below the configured percent of the instalment (decision 6). Leniency does not pause interest.
- Service fee pro-rata is only the opening period from disbursement to the first due date. Later months, including the settlement month, are the full monthly fee, capped at R60 (decision 9).
- When the repo rate falls, the provider's stored choice applies. There is no platform default (decision 11).
- The in-duplum cap is cumulative. Its base includes pre-default capitalised initiation (decision 7).

Still open:

- The early-termination base is unsettled, and Day-1 does not reach it. See the last example.
- Credit life and funeral cover on a lay-by that secures a loan: the locked decisions say the treatment is undefined (estate versus beneficiary, and the effect on the loan). This schema does not store a choice.
- The opening-period service-fee fraction uses the actual days in the disbursement month as its denominator. Decision 9 names the period and does not name that denominator.
- Leniency is calendar days. The locked text says "days" and does not say business days.
- Decision 13 (instalment adjustment when disbursement is later than the quote) and decision 14 (payment frequency) are locked and are not columns yet. Servicing must read the document before storing either choice. Do not invent a default.

### Initiation fee

Table B for a short-term or unsecured agreement is R165 plus 10 percent of the amount above R1 000, never above R1 050. Regulation 43(3) says the fee may never exceed 15 percent of the principal debt. The 2006 regulations say the Table B amount is the amount deferred. GN 1080 substituted the table; the fetched notice did not restate that note. Confirm the note survived.

Paid upfront on a R1 000 advance, the amount deferred is R1 000. Table B is R165. Fifteen percent is R150. The cap is **R150**. There is no circularity.

Deferred into the principal, both limbs are circular. The largest fee that satisfies the grossed reading is the fixed point of those formulas.

| Cash advanced | Adopted (cash base) | Grossed fixed point | Gap |
| --- | --- | --- | --- |
| R1 000 | R150.00 | R176.47 | R26.47 |
| R2 000 | R265.00 | R294.44 | R29.44 |
| R8 000 | R865.00 | R961.11 | R96.11 |

Day-1 charges the cash-base column. On every amount tested it is less than or equal to the grossed column.

### VAT

GN 1080 states rand amounts and does not mention VAT. Adding 15 percent on top of the R265 fee charges **R304.75**, which is **R39.75** more than the gazetted figure. On the R786.36 capitalised short-term fee the gap is **R117.95**, and deferring that extra VAT would also push a full-size short-term loan through the R8 000 ceiling.

Day-1 treats the gazetted figure as the most the consumer pays. A VAT vendor splits it. On R265.00 the split is R230.43 plus VAT of R34.57. The parts add back to R265.00. They can disagree with `exclusive × 15%` by a cent; that is the split, not a higher charge.

### Subsequent short-term loan

Table A says "5% per month on the first loan and 3% per month on subsequent loans within a calendar year". It does not say whether "first" resets each January.

On a R1 000 balance the two readings are **R50** and **R30** for a month. Day-1 counts every later disbursed short-term loan with the same organisation as subsequent, including a loan originated in a new calendar year. The calendar-year reset is the alternative, and it charges more. The contractual rate on the first loan may still be 5 percent. The engine applies 3 percent when the ordinal is 2 or more. A quote that never paid out does not move the ordinal.

### In duplum

Section 103(5): the section 101(1)(b) to (g) amounts that accrue while the consumer is in default may not, in aggregate, exceed the unpaid principal at the time the default occurs. Locked decision 7: that principal includes initiation capitalised before the default. Initiation that was not capitalised stays a fee. Post-default interest and fees stay charges even if a statement shows them as capitalised. A payment reduces what is owed and does not reset the counter.

The same default test feeds this cap and collections. It does not flag during the leniency period. Interest still accrues on those days.

The cap is cumulative for that episode. The episode ends when nothing payable is overdue. The next default snapshots principal again.

Alternative: the cap is on the unpaid stock of those charges, so paying them creates room to accrue more.

Worked, actual-days short-term at 5 percent, service fee R60, principal at default R1 000, no other opening balances. The month's interest on a constant base is exactly 5 percent, then half-up.

| Month | Interest | Service fee | Accrued during the default | Deferred amount |
| --- | --- | --- | --- | --- |
| 1 | R50.00 | R60.00 | R110.00 | R1 110.00 |
| 2 | R55.50 | R60.00 | R225.50 | R1 225.50 |

A R200 payment then falls on section 126: interest R105.50, fees R94.50, principal unchanged. Fee balance left is R25.50. The accrual counter stays R225.50.

The cumulative reading stops when accrued charges reach **R1 000.00**, in month 9. The floating reading, given the same payment, accrues **R1 200.00** by month 10, because the R200 is room again. The gap equals the charges the consumer paid during the default. With no payment, both readings stop at R1 000.

### Section 126

A R500 payment. Payable interest R80. Service fee R60 payable on 1 March. Default administration R40 payable on 15 March. Principal R1 000.

| Tier | Applied | Left of the payment |
| --- | --- | --- |
| Interest | R80 | R420 |
| Service fee, older | R60 | R360 |
| Default administration | R40 | R320 |
| Principal | R320 | R0 |

Principal left is R680. Holding R320 as a suspense credit for the next instalment is the alternative, and it is not what section 126(3)(c) says. The receipt has to show the split, because the consumer may have meant to cover the next instalment and will otherwise fall due again.

Two fees payable the same day share a short payment in proportion. R45 against a R60 fee and a R30 fee the same day is R30 and R15. The total applied to fees does not change; only which fee is cleared does. Where the cents do not divide, the largest remainder gets the extra cent, and the fee code breaks a tie.

### Day count

Locked decision 5: the credit provider chooses actual/actual or 30/360. Actual/actual is the recommendation for a new product. 30/360 remains selectable. A 30/360 divisor can differ from the regulation 40 prescribed divisor by more than the 0.1 percent annual tolerance. The terms version pins the choice anyway. The regulation 40 codes stay in reference data so an agreement already pinned to one of them can still be read.

Regulation 40, R1 000 at 5 percent a month, March 2026 (31 days):

| Convention | Interest for the month |
| --- | --- |
| Actual days in the month | R50.00 |
| Divisor 30, charged on all 31 days | R51.67 |

The gap is R1.67, about 3.3 percent of that month, which is more than the 0.1 percent annual tolerance. Both divisors are permitted. They are not interchangeable, and the terms version pins one. The short-term template pins actual/actual. The same point applies to 365 against 366 for an annual rate, and to 360: the agreement picks one.

Unsecured, R10 000, 28.25 percent, divisor 365, 31 days: **R239.93**.

### Service fee in the opening period

Locked decision 9. Pro-rata only from the disbursement value date to the first payment due date. The denominator used here is the actual number of days in the calendar month of disbursement, and the result is clamped to one monthly fee. Every later month, including the settlement month, is the full contractual monthly fee, still not above R60. A product cannot prorate the settlement month.

Disbursed on 20 March 2026, first due on 3 April 2026: 14 days of a 31-day month. `6000 × 14 / 31` is 2709.67 cents, floored to **R27.09**. A first due date of 20 April is 31 days, so the opening fee is the full **R60**. A settlement on 2 April of a later month is still **R60** when the contractual fee is R60.

The older calendar-month reading, which regulation 44(4) does not settle by itself, remains measurable and is not what is charged. Including the conclusion day on 20 March is R23.22 and excluding it is R21.29. The one-day gap is R1.93. Decision 9 replaces that choice.

### Settlement

Section 125(2) is unpaid principal, plus unpaid interest and other fees up to the settlement date. The early-termination charge in section 125(2)(c) exists only for a large agreement.

A small agreement, unpaid principal R800, unpaid interest R25, unpaid service fee R60, settles for **R885**. Adding an early-termination cent is rejected.

R250 000 is large (section 9: at or above the higher threshold). R249 999.99 is intermediate. The Day-1 unsecured template stops at R249 999.99 so the unsettled charge is not reached.

If a large agreement is ever boarded: no prescribed charge was found in the 2006 regulations or in GN 1080, so section 125(2)(c)(i) points at sub-paragraph (ii). On the constant-balance reading, R250 000 at 28 percent, divisor 365, no notice, from 15 October 2026 to 15 January 2027 (92 days), the ceiling is **R17 643.83**. Three months' notice makes it zero. The scheduled-instalment reading would be lower, because instalments would have reduced the balance. That is why the template stays under the line.

### Lay-by and the security deposit

Goods priced at R2 000. The regulation 34 maximum penalty is **R20**. The consumer has paid R800.

| Facts | Penalty | Refund |
| --- | --- | --- |
| Penalty disclosed before the agreement | R20 | R780 |
| Not disclosed | R0 | R800 |
| Consumer died or was hospitalised | R0 | R800 |

A cash deposit securing a short-term loan is not this. CPA section 62 is about goods held until the price is paid. The deposit accrues no interest and takes no 1 percent penalty. Applying the penalty there would be an invented charge. Interest on the loan accrues on the loan principal minus the lay-by hold, and not below zero. Only the loan carries a service fee. Set-off against the loan needs a mandate id; section 124's conditions on a charge against a named deposit are enforced by servicing, and the configuration flag is what makes a missing mandate fail closed. Credit life and funeral cover on that lay-by are not decided and are not stored.

### Zero-cost BNPL

Section 8 generally requires a fee, charge, or interest before an arrangement is a credit facility or a credit transaction. A plan with no charge is not given an NCA price. The template rejects a R20 late fee. If the business wants that fee, the product is republished as incidental credit: initiation nil, interest at most 2 percent a month, and the incidental-credit timing rules in the Act apply from when the charge becomes payable. The engine does not reclassify on its own.

## Failure closed

The posting does not proceed when:

- the cap row, the confirmed repo rate, or the adopted interpretation set does not cover the business date
- the contractual charge is above the ceiling (publish is rejected; an already-pinned rate is reduced, not honoured)
- a short-term deferred amount would exceed R8 000, or the term would exceed 6 months
- a zero-cost or lay-by product carries an NCA charge
- default administration or collection costs are posted with no tariff row
- an early-termination charge is asked for on an agreement that is not large
- currency is not ZAR, or the organisation timezone is not Johannesburg
- the audit row cannot be appended

## What was read

- National Credit Act 34 of 2005, Gazette 28619: sections 2(5), 7, 9, 101, 102, 103, 104, 105, 125, 126.
- National Credit Regulations, GN R489 of 31 May 2006: regulations 39, 40, 42, 43, 44, 46, 47, 55, 56, in a consolidated text. The historical rand amounts in that text are the pre-2016 ones.
- GN 1080, Gazette 39379, 6 November 2015, effective 6 May 2016: Tables A and B, the R60 service fee, regulation 44(3) and 44(4), and the "new agreement only" initiation rule.
- GN 713, Gazette 28893, 1 June 2006: the R15 000 and R250 000 thresholds.
- CPA section 62 and regulation 34: the lay-by penalty.
- SARB MPC statement of 23 September 2026, as reported by SAnews and the October 2026 Monetary Policy Review: 7.25 percent effective 25 September 2026.

Paulsen and the other in-duplum judgments were not re-read for this pass. The cumulative reading is taken from the words "accrue" and "in aggregate" in section 103(5), and it is marked pending counsel. The secondary report of a 7.00 percent repo rate from 29 May 2026 is not seeded.
