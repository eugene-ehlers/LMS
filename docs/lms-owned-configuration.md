# LMS configuration, reference data, and audit

`docs/LOCKED_DECISIONS.md` (last updated 2026-10-27) is the source of truth for calculation, ledger, servicing, and configuration behaviour. This document is the storage and the read path. Where the two differ, the locked decisions win. Do not invent a default for a choice that document leaves open. The implementation checklist, including draft signatures and the points the lock does not settle, is [docs/IMPLEMENTATION_CHECKLIST.md](docs/IMPLEMENTATION_CHECKLIST.md).

This note was aligned to the locked decisions after the Layer 0 points were closed. The Python and SQL already in the repository were not changed in that alignment. Where they still disagree with the lock, the checklist lists the disagreement. The code is not a second rule.

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
| Name, ID number, service address | Enigma, frozen at booking (decision 16) | No. A later change in Enigma does not rewrite the concluded agreement |
| Contractual rate as base rate minus campaign discount | The terms. The performing rate is base minus discount, and may be zero. The discount stays through the leniency window. It falls away on the default flag date. It does not return if the account is later cured. The rate is then the base. Penalty interest is that rate, so it does not exceed the contract | The base and the discount are pinned. A later campaign does not reprice this agreement |
| `leniency_days`, `full_payment_threshold_percent` | Organisation, unless the product overrides it. Copied onto the agreement. Null at either resolved value fails closed. Leniency counts calendar days, including weekends and public holidays. The examples 4, 5, and 95 are not defaults | No |
| Threshold instalment | For the due date being tested: the original principal slice, plus levied charges that share that due date (monthly service fee, non-capitalised initiation fee, and credit life). Unbilled interest is excluded until it is debited. The amount received is the amount received for that due date | No |
| `interest_on_deferred_initiation` | Organisation, optional product override. Decision 10 names `none` as the substantive default. Decision 19 says an unset value fails closed, so the column is nullable and the provider stores `none` or `permitted`. Null is not filled in | No |
| `repo_rate_fall` | Organisation, optional product override. Decision 11 and decision 19. `contract_rate` or `lower_of_contract_and_cap`. Null fails closed | No |
| `day_count` | Organisation, optional product override. Decision 5: `actual_actual` (recommended for a new product) or `thirty_360`. A credit product with neither set fails closed. A 360-day year is not required for a Day-1 product. Both conventions stay available | No |
| `vat_on_rand_maxima` | Organisation, optional product override. Decision 9 and decision 19. `exclusive` or `inclusive`. Null fails closed. Storing `exclusive` is how the provider takes the decision 9 treatment of R60, R165, and R1 050 | No |
| `late_disbursement` | Organisation, optional product override. Decision 13 and decision 19. `adjust_instalment` or `keep_instalment`. Null fails closed | No |
| `partial_prepayment` | Organisation, optional product override. Decision 13 and decision 19. `shorten_term` or `drop_instalment`. Null fails closed. The preference to keep the contractual instalment is not a silent default | No |
| Campaign `base_rate` and `discount_rate` | Organisation pair, optional product pair. Decision 3. The pair inherits together. A product discount of zero is not read while the product base is null. Zero is a valid effective rate | The resolved pair is pinned. A later campaign does not reprice this agreement |
| `short_term_ordinal` | Decision 13: a subsequent short-term loan is counted per credit-provider organisation and per calendar year. A quote that does not disburse does not count | The count restarts in January. The organisation scope does not change |
| `ncr_registration_number` | Enigma, copied at origination. This copy is a design fact. It is not one of the three fields decision 16 freezes | No |

The statutory ceiling is not pinned. On each accrual date the engine reads the cap in force that day. A short-term monthly cap is applied on every accrual, because it is the cap for that loan's ordinal. For a repo-linked rate, locked decision 11 is a provider choice stored as `repo_rate_fall`: `contract_rate` keeps the contract rate when the repo falls, and `lower_of_contract_and_cap` accrues at the lower figure and the section 104 notice is issued. Null fails closed. Section 104 still forbids a unilateral increase, so a later rise in the cap does not raise a fixed contract. A rate above the cap on the origination date is refused, including a campaign base that would apply only after the discount falls away.

Sub-ledgers the future ledger has to keep, because section 126 and section 103(5) need them separate even after regulation 40 adds interest to the deferred amount:

`principal`, `interest`, `initiation_fee`, `service_fee`, `default_admin`, `collection`, `credit_insurance`, `deposit`, `layby_penalty`, `early_termination`.

The interest base for the next day is the outstanding balance decision 6 names, minus a linked lay-by hold, and minus a deferred initiation fee unless the provider stored `permitted`. Decision 4 says the hold reduces only the interest base. Principal stays gross for in duplum and for settlement. The lock does not say the hold is posted through section 126. A capitalised initiation fee is part of `principal` (decisions 2 and 7), including inside the in-duplum ceiling when it was capitalised before the default date. Day-1 short-term and unsecured stay non-capitalised (decision 2). `initiation_capitalised` defaults to false and publish rejects true for the Day-1 classifications. The same capitalised-versus-due-fee logic applies to related fee points. The lock does not name those related points. Post-default interest and fees stay in their own sub-ledgers even when a statement shows them as capitalised. Charges that cause the default do not count toward the in-duplum cap. Only charges that accrue during the default episode do.

## How the engine reads configuration

One `REPEATABLE READ` transaction. No call to Enigma. If a required row is missing, the posting fails. A missing fee means zero, never "use the cap".

1. **Agreement pin**, including the terms version id and the short-term ordinal.
2. **`cfg_product_terms` by primary key.** Not "whatever is current".
3. **`cfg_fee_rule` and `cfg_instrument` for that version.**
4. **`ref_interest_cap`** whose span covers the Johannesburg business date, for the pin's classification.
5. **`ref_initiation_fee_cap`**, **`ref_service_fee_cap`**, **`ref_charge_rule`**, **`ref_threshold`** the same way, when the posting is a fee, a size test, or a short-term limit.
6. **`ref_reference_rate`** code `SARB_REPO`, `confidence = 'confirmed'`, covering that date. A variable rate, and any `RR + margin` cap, fails closed without it.
7. **`ref_interpretation_set`** with status `adopted` covering that date, and its choices. The set id is written on the audit row.
8. **Resolved elections** from `cfg_organisation_settings` with the product override: leniency, threshold, campaign pair, day count, `vat_vendor`, and the decision 19 elections (`vat_on_rand_maxima`, `late_disbursement`, `partial_prepayment`, `interest_on_deferred_initiation`, `repo_rate_fall`). Unset fails closed. This read does not call Enigma. Decision 15's fail-closed rule for a timeout, an ambiguous status, or a suspended enrolment is the boundary of that call, which this repository does not make.
9. **`ref_tariff_amount`** when the posting is default administration or collection. A missing row fails that posting (decision 18). An interest accrual does not require a tariff row.
10. **Post the ledger and the audit rows in the same transaction.** If the audit insert fails, the ledger rolls back. The seal assigns `recognition_sequence` (decision 1).

Business dates are `Africa/Johannesburg`. `2026-10-31 22:30 UTC` is `2026-11-01` in Johannesburg. Day-1 organisation settings reject any other zone, so a tenant cannot move a due date across a cap change by picking a timezone. South Africa does not observe daylight saving; the zone is still named rather than hard-coded as UTC+2.

`cfg_cache_generation` increments when terms or flags change. Caps and holidays may be cached against that generation. A terms version is not cached past the request that pinned it.

The SQL for steps 2, 4, and 6, and the ordinal query the servicing table must answer, are in `src/lms_config/context.py`.

### Rate the engine then uses

Short-term and incidental caps are monthly rates. They are not converted to an annual rate for the cap test. Regulation 42 requires those two to be disclosed as a monthly rate. Five percent a month is the cap, not "60 percent a year" and not the compounded equivalent.

Unsecured and the other Table A annual rows are `repo + margin`. On 26 October 2026 the confirmed repo rate is 7.25 percent (MPC statement of 23 September 2026, effective 25 September). The unsecured ceiling is 28.25 percent a year.

```text
performing = base_rate - discount_rate          # may be zero for the whole term or part of it
rate       = performing                         # through the leniency window, and while not in default
           = base_rate                          # from the default flag date; this does not reverse on a later cure
chargeable = rate                               # repo_rate_fall = contract_rate, after origination
           = min(rate, statutory)               # short-term monthly cap, or repo_rate_fall = lower_of_contract_and_cap
```

A zero rate or a zero fee must calculate. A campaign that displays base x percent and discount y percent, with x minus y equal to zero, is a real zero rate, not a missing price. Penalty interest is the base once the discount has fallen away, and that base is the contractual rate at that point, so the penalty does not exceed the contract. The lock does not say whether the discount is removed before or after the flag-date payment is tested. The morning check does see that payment.

### A payment, in order

1. Resolve the value date and the rows above. The value date is the system recognition date. Start of that day is 00:00. A loan, settlement, deposit, or payment recognised on a calendar day is treated as 00:00 that day. A reversal uses the value date the system originally recognised, not the calendar day of the reversal entry.
2. Interest since the last posting is the sum of the daily amounts on the outstanding balance. Leniency does not remove or reduce a day. A payment recognised on a default flag date is visible to the morning default check. The lock does not say what value date applies when the system recognises an event on a later calendar day than the day the consumer concluded it.
3. Decision 17: round half-up to the cent on billing, use that same rule wherever rounding is required, and disclose the annual equivalent rate. Rounding must not create a compliance breach. The example in the lock is an instalment rounded up above the affordability figure already aligned with the client. The code currently floors a statutory cap so the posted cent cannot exceed the gazetted figure. That is a divergence, not a second locked rule. The formula for the annual equivalent rate is not in the lock.
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
| Short-term interest | 5% a month, and 3% a month on a subsequent loan | Table A item 5. Decision 13 counts subsequent per credit-provider organisation. The notice's "within a calendar year" is not restated by the lock |
| Incidental interest | 2% a month | Table A item 7 |
| Other Table A margins | Mortgage RR+12, facility RR+14, developmental RR+27, other RR+17 | Same notice |
| Initiation, short-term and unsecured | R165 + 10% of the amount above R1 000, never above R1 050, and never above 15% of the principal debt | Table B and regulation 43(3) |
| Incidental initiation | Nil | Table B |
| Service fee | R60 a month, excluding VAT unless the provider elects inclusive | Regulation 44 as substituted by GN 1080, and decision 9. Pro-rata only in the opening month. Full monthly fee thereafter, including the settlement month |
| Short-term definition | Deferred amount at inception not above R8 000, repayable within 6 months | Regulation 39(2) |
| Agreement size | Small at or below R15 000, large at or above R250 000 | GN 713, GG 28893, 1 June 2006, section 7(1)(b). Section 9 |
| Lay-by penalty | At most 1% of the full purchase price | CPA section 62 and regulation 34 |
| Repo rate | 7.25% from 25 September 2026 | SARB MPC statement, 23 September 2026 |

Default administration (regulation 46) and collection costs (regulation 47) are tariff references, not rand caps. No tariff was transcribed in this pass. The posting fails closed. That is deliberate.

The 2006 initiation and service-fee figures were replaced on 6 May 2016 and are not seeded. An accrual before that date fails closed. Pre-2016 books are out of scope until those rows are loaded from the 2006 text.

A gazette sweep from 2016 through October 2026 was not completed for every threshold. The 11 May 2016 consolidation still shows R15 000 and R250 000, and the amendment found from that date changes the section 42 registration threshold, not section 7(1)(b). Confirm there is no later amendment before go-live. A later amendment is a new row.

## Configuration

Every configuration row carries `organisation_id` except the child rows of a product, which inherit it through `cfg_product`.

`cfg_organisation_settings` is one row per organisation: Johannesburg timezone, ZAR, locale, and `vat_vendor`. It also stores the elections in the table above. No legal name, no NCR number. "Customer" in locked decision 6 is this organisation. A product column of the same name overrides it. Null does not mean zero days, 100 percent, `none`, or `exclusive`.

`cfg_brand` is display name, support contacts, logo key, statement footer. Presentation only.

`cfg_feature_flag` is an effective-dated insert. The catalogue is `origination_enabled`, `debit_orders_enabled`, `statements_enabled`, `bnpl_enabled`, `layby_security_enabled`. Overlapping spans for the same flag are rejected.

`cfg_product` is the stable id. `enigma_enrolment_code` is the code Enigma uses. The row does not grant enrolment.

`cfg_product_terms` is the priced version. `rate_kind` is `zero`, `fixed_monthly`, `fixed_annual`, or `variable_rr_plus`. A null rate column on a fixed kind means the product inherits the organisation campaign. When the product sets a base, the effective column must equal base minus discount, including zero (decision 3). `day_count_code` null inherits the organisation (decision 5). `intraday` is `start_of_day` (decision 1). `prorate_settlement_service_fee` cannot be true (decision 9). The same row may override every decision 19 election, plus leniency and the threshold (decision 6). `payment_frequency` is one of the decision 14 codes, or null. The lock does not say a null frequency fails closed. `initiation_capitalised` is false for Day-1 (decision 2).

`cfg_fee_rule.charge` is `zero`, `fixed`, `statutory_formula`, or `tariff`. Initiation is published as `statutory_formula` so the engine caps each agreement. A fixed initiation amount is rejected at publish, because an amount that is lawful on R8 000 can break the 15 percent limb on a smaller loan. `tariff` is how default administration and collection are represented, and it still cannot post without `ref_tariff_amount`.

`cfg_instrument.kind` is `credit`, `security_deposit`, or `cpa_layby`. A linked lay-by uses the deposit kind today. Decision 4 requires a parent/child pair treated as one loan, not as security that would make the loan a secured loan. The kind name is a schema label, not that classification. Set-off without an Enigma mandate id is refused. Death may not apply the lay-by unless a section 124 authority was signed in life. The deposit is not a CPA lay-by of goods, so the 1 percent penalty is not available on it. One monthly service fee is levied on the parent.

### Day-1 templates

`src/lms_config/templates.py`. A tenant may charge less. Publish runs `validate_terms`.

| Template | Classification | Price | Shape |
| --- | --- | --- | --- |
| Micro / short-term | `short_term` | 5% a month contractual. The engine cuts a later loan to 3% | Actual days in the month. Term at most 6 months. Deferred amount at most R8 000. Initiation by formula. Service fee R60 |
| Unsecured personal | `unsecured` | RR + 21% | Divisor 365. Commercial maximum principal R249 999.99, which is below the large-agreement line on purpose |
| BNPL | `zero_cost` | Nothing | Any positive rate or fee is rejected. A late fee is a new product, classified `incidental` (2% a month, initiation nil), not a flag on this one |
| Lay-by of goods | `cpa_layby` | No interest | Cancellation penalty is the statutory formula, and the engine still returns nil if it was not disclosed or the consumer died or was hospitalised |
| Linked lay-by | `short_term` parent plus a child hold | The loan is priced as short-term. The hold is 0%. Interest is on principal minus the hold | One service fee, on the parent. Not a secured-loan classification. Not a CPA penalty. Day-1 treats the arrangement as deposit-insurance style, and not as deposit-taking under the Banks Act |

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

Locked by `docs/LOCKED_DECISIONS.md` and reflected in this note:

- Value date is the system recognition date at 00:00. Reversals reuse the original value date. A flag-date payment is visible to the morning default check (decision 1).
- A capitalised fee is principal. A fee that is not capitalised is a section 126 charge. Pre-default capitalised initiation sits inside the in-duplum ceiling (decision 2).
- Zero rates and zero fees calculate. Campaign price is base minus discount. The discount survives leniency, falls away on the flag date, and does not return on cure (decision 3).
- A linked lay-by is a child of the loan. The pair is one loan. Interest is on the net balance. One service fee, on the parent. Credit life, funeral, death, and the Day-1 deposit-insurance characterisation are stated in decision 4.
- Day count is actual/actual or 30/360, chosen by the provider. Accrual is daily. A 360-day year is not required for Day-1 (decision 5).
- One default test for in duplum and for collections. Leniency is calendar days. Unset leniency or threshold fails closed. The threshold instalment is defined in decision 6.
- In duplum is an episode ceiling, not a lifetime ceiling. A cure closes the episode. The next default takes a new ceiling. Three unnamed section 103(5) edges stay unsigned and the clip stays off until counsel confirms (decision 7).
- Section 126 order is interest, then fees or charges, then principal (decision 8).
- Service-fee pro-rata is the opening month only. The fraction is the days from the disbursement date to the day before the first due date, over the actual days in the disbursement month. Later months, including settlement, are the full monthly fee, subject to the R60 cap. The named rand maxima are excluding VAT unless the provider stores `inclusive` (decision 9, decision 19).
- Interest on a deferred initiation fee is `none` or `permitted`, stored per organisation with a product override. Unset fails closed (decision 10, decision 19).
- A fall in the repo rate is `contract_rate` or `lower_of_contract_and_cap`, stored the same way. Unset fails closed (decision 11, decision 19).
- One statement per client per credit-provider organisation shows all of that client's loans with that organisation. Each loan keeps its own opening and closing balance (decision 12).
- External decision engines must be acceptable. Late disbursement and partial prepayment are stored elections (decision 13, decision 19). Extra costs are a further monthly fee, not capitalised into the schedule. Restructuring can set a new instalment, price, and term. Subsequent short-term loans are counted per organisation and per calendar year (decision 13).
- Frequencies are weekly, fortnightly, monthly, quarterly, bi-annual, and annual (decision 14).
- Enigma owns identity. The LMS stores opaque ids and fails closed on timeout, an ambiguous status, or a suspended enrolment (decision 15).
- Name, ID number, and service address freeze at booking (decision 16).
- Billing rounds half-up to the cent, everywhere rounding is required, and must not create a compliance breach. The disclosed annual equivalent is the periodic rate times the number of periods in the year, a simple nominal, and both rates are disclosed (decision 17).
- Tariff amounts fail closed until a row exists. Allowable extra costs are preferred as an additional monthly fee (decision 18).
- VAT, late disbursement, partial prepayment, interest on deferred initiation, and the repo-rate fall are organisation elections with an optional product override. Unset fails closed (decision 19).

Still not settled by the lock, so this note does not choose them:

- The early-termination base for a large agreement. Day-1 unsecured products stay below R250 000 so the charge is not reached.
- Which three section 103(5) edges are unsigned, and whether "the clip stays off" suspends only those edges or the episode ceiling stated in the same section.
- Whether a late system recognition keeps the calendar day the consumer concluded, or moves the value date to the recognition day. Decision 1 states both "system recognition date" and "the calendar day" of conclusion. This repository uses the Johannesburg calendar date of the recognised instant. It does not invent backdating.
- Which balance is compared when the lay-by is at least the settlement balance. Decision 4 says principal stays gross. It does not say whether "settlement balance" is already net of the hold.
- Which credit-life branch applies on Day-1. The lock gives a cash-deposit branch and an insurance branch, and also says the Day-1 arrangement is deposit-insurance style.
- The shape of a service address, the weekday a weekly instalment uses, and whether a restructure is a new agreement or an amendment of the frozen one.

The checklist holds the same gaps with the integers a reader would otherwise invent.

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

Decision 9: the rand maxima R60, R165, and R1 050 are excluding VAT by default. The provider may elect inclusive. Decision 19 stores that election on the organisation, with an optional product override, and an unset value fails closed. The column is nullable. Storing `exclusive` is the provider's act of taking the decision 9 treatment. The lock names those three maxima. It does not say that every other gazetted rand amount follows them.

On a R265 initiation fee the two elections differ by **R39.75** (R304.75 against R265.00). On the R786.36 capitalised short-term fee the gap is **R117.95**. Adding that VAT to a loan already at the R8 000 deferred-amount line pushes it through the line. That interaction is a consequence of the exclusive default. It is not a new cap.

The earlier reading, that the gazetted figure is already the most the consumer pays, is the inclusive election. It is no longer the default. A split of an inclusive R265.00 into R230.43 plus VAT of R34.57 remains the arithmetic of that election. The shipped interpretation `vat_on_prescribed_cap = cap_is_consumer_maximum` still records the old default. The lock wins.

### Subsequent short-term loan

Table A says "5% per month on the first loan and 3% per month on subsequent loans within a calendar year". Decision 13 counts a subsequent loan per credit-provider organisation and per calendar year. January can be a first loan again. A quote that never disburses does not count.

On a R1 000 balance the two rates are **R50** and **R30** for a month. The contractual rate on a first loan in that year may still be 5 percent. The 3 percent cap is the subsequent-loan cap once the ordinal is subsequent. The ordinal query filters disbursements in the calendar year of the business date, for the same organisation and person.

### In duplum

Section 103(5): the section 101(1)(b) to (g) amounts that accrue while the consumer is in default may not, in aggregate, exceed the unpaid principal at the time the default occurs. Decision 7 defines that ceiling per episode.

- The ceiling is unpaid principal, including initiation capitalised before the default date, at the date of first default in that episode.
- Post-default accruals stay charges even if a statement shows them as capitalised.
- Charges that cause the default do not count toward the cap. Only charges that accrue during the episode do.
- A payment during the episode reduces what is owed and does not reset that episode's counter.
- A cure closes the episode.
- The next default starts a new episode and a new ceiling from the unpaid principal at the start of that default.
- This is not a single ceiling for the life of the loan.
- Three section 103(5) edges not decided by Nedbank v NCR [2011] ZASCA 35 remain unsigned. The clip stays off until counsel confirms. The lock does not name the three edges.

The same default test feeds this ceiling and collections. It does not flag during the leniency period. Interest still accrues on those days. The discount stays on through that window.

The floating reading, in which a payment of charges creates room to accrue more inside the same episode, is not the locked reading.

The table below is the cumulative arithmetic of one episode on a constant balance. It counts the service fee from month 1. Decision 7 now excludes charges that cause the default, and it leaves the clip off until the unnamed edges are confirmed. The table is not a posting instruction while those two sentences stand.

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

Decision 8 now orders fee buckets that are already due: collection costs, default administration, credit insurance, service fee, initiation fee, and within a bucket the earliest due date first. The allocation function in this repository still shares a short payment on the same day in proportion, oldest date first. That function is unchanged in this pass. It does not yet follow the bucket order. R45 against a R60 fee and a R30 fee the same day is still R30 and R15 in that function.

### Day count

Decision 5: the credit provider chooses actual/actual or 30/360. Actual/actual is the recommendation for a new product. 30/360 remains selectable. A 360-day year is not required for Day-1. Accrual is daily. A 30/360 divisor can differ from the regulation 40 prescribed divisor by more than the 0.1 percent annual tolerance. The terms version pins the choice anyway. The regulation 40 codes stay in reference data so an agreement already pinned to one of them can still be read.

Regulation 40, R1 000 at 5 percent a month, March 2026 (31 days):

| Convention | Interest for the month |
| --- | --- |
| Actual days in the month | R50.00 |
| Divisor 30, charged on all 31 days | R51.67 |

The gap is R1.67, about 3.3 percent of that month, which is more than the 0.1 percent annual tolerance. Both divisors are permitted. They are not interchangeable, and the terms version pins one. The short-term template pins actual/actual. The same point applies to 365 against 366 for an annual rate, and to 360: the agreement picks one.

Unsecured, R10 000, 28.25 percent, divisor 365, 31 days: **R239.93**.

### Service fee in the opening period

Decision 9. Pro-rata only in the opening month, described as disbursement to the first payment due. The fraction is inclusive days in the month divided by the actual days in that month. Every later month, including the settlement month, is the full monthly fee, subject to the R60 cap. A product cannot prorate the settlement month. The R60 cap is excluding VAT unless the provider elects inclusive.

Decision 9 defines that count as the inclusive calendar days from the disbursement date to the day before the first due date. Date subtraction is that count. For 20 March 2026 to 3 April 2026 it is 14/31. The function floors that to R27.09. Decision 17's half-up rule, applied to the unrounded 2709.68 cents, is a separate question: half-up must not create a compliance breach, and this note does not choose which sentence wins for a statutory cap.

A settlement in a later month is the full contractual monthly fee, still subject to the cap.

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

A lay-by linked to a loan is not this CPA goods lay-by. Decision 4:

- The pair is parent and child, and the contracts treat it as one loan. It is not security that would make the loan a secured loan.
- Payments can be allocated across the loan and the linked lay-by.
- Interest is calculated on loan principal minus the lay-by hold. The hold reduces only the interest base. Principal remains gross for in duplum and for settlement (decision 4).
- One monthly service fee, levied on the parent.
- The client can consolidate or settle when the lay-by is at least the settlement balance.
- Credit life pays the loan first. The lay-by covers any shortfall. Surplus goes to the estate if the lay-by is treated as a cash deposit. If it is structured as insurance, treatment follows whether a beneficiary was named.
- A funeral benefit is paid to the named beneficiary. The loan and the lay-by are left as they are.
- Death may not apply the lay-by unless a section 124 authority was signed in life. Otherwise the lay-by stays with the estate.
- Day-1 is a deposit-insurance style arrangement: the client pays for a period, then the loan is disbursed. It is not deposit-taking under the Banks Act for Day-1 purposes.

The CPA 1 percent penalty is not available on the hold. The code still labels the child `security_deposit` and requires an Enigma mandate id before set-off. Those are schema facts. They do not reclassify the loan as secured.

### Zero-cost BNPL

Section 8 generally requires a fee, charge, or interest before an arrangement is a credit facility or a credit transaction. A plan with no charge is not given an NCA price. The template rejects a R20 late fee. If the business wants that fee, the product is republished as incidental credit: initiation nil, interest at most 2 percent a month, and the incidental-credit timing rules in the Act apply from when the charge becomes payable. The engine does not reclassify on its own.

## Statements, instalments, and extra fees

Decision 12: one statement per client per credit-provider organisation, showing all of that client's loans with that organisation. Each loan keeps its own opening and closing balance. The statement does not cross organisations.

Decision 13, when disbursement is later than the quote date, both of these must be possible:

- adjust the instalment from the actual disbursement date and the remaining term
- keep the original instalment, and either settle early or write off a small residual at the contractual end. The write-off is not required if the account is already in default

After a partial prepayment the provider chooses `shorten_term` or `drop_instalment`. Decision 19 stores that choice on the organisation, with a product override. Unset fails closed. The preference to keep the contractual instalment is not written in as a default. Late disbursement is `adjust_instalment` or `keep_instalment`, stored the same way.

Fees other than interest, initiation, the monthly service fee, and credit life are added as a further monthly fee, fixed or variable. They are not capitalised into the amortisation schedule. Collection costs are the example. Decision 18 says the same preference for allowable extra costs, and the posting still fails closed until a tariff row exists.

A restructuring can create a new instalment, price, and term during the life of the loan. The lock does not say whether that is a new agreement, with a new pin, or an amendment. Decision 16 stops a later Enigma identity change from rewriting the concluded agreement. It does not say a restructure is forbidden.

Decision 14 requires weekly, fortnightly, monthly, quarterly, bi-annual, and annual frequencies. It does not say which weekday a weekly date uses, or whether fortnightly means fourteen days.

Credit life is part of the loan instalment for affordability, and it is one of the levied charges in the default-threshold instalment when it shares that due date. The lock does not restate an affordability formula.

Decision 17 discloses the periodic rate and the nominal annual rate. The nominal annual rate is the periodic rate times the number of periods in the year. `nominal_annual_rate` takes that integer from the caller. The lock does not say whether weekly means 52 or 365/7.

## Failure closed

The posting does not proceed when:

- the cap row, the confirmed repo rate, or the adopted interpretation set does not cover the business date
- leniency, the full-payment threshold, the campaign pair on a credit product, day count on a credit product, or any decision 19 election is unset
- `repo_rate_fall` is unset, including on a monthly short-term product, because decision 19 lists it
- the contractual rate, including a campaign base that would apply once a discount falls away, is above the statutory maximum on the origination date
- default administration or collection costs are posted with no tariff row (decision 18)
- a short-term deferred amount would exceed R8 000, or the term would exceed 6 months
- a zero-cost or lay-by product carries an NCA charge
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

Decision 7 aligns the episode ceiling with section 103(5) and Nedbank v NCR [2011] ZASCA 35, subject to a fresh ceiling on a later default. Three unnamed edges of that section remain unsigned, and the clip stays off until counsel confirms. Paulsen was not re-read for this note. The secondary report of a 7.00 percent repo rate from 29 May 2026 is not seeded.
