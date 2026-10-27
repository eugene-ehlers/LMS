# Implementation checklist

Documentation only. This file does not change `src/lms/calc/`. It records what [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) requires after the 27 October 2026 Layer 0 update, and where an implementer does not yet have enough named structure to write code without inventing a rule.

The calculation contract and the worked examples stay in [day1-calculation-rules.md](day1-calculation-rules.md). Pins in `tests/test_day1_examples.py` and `tests/test_locked_alignments.py` describe the calculator as it is. They are not a licence to keep a behaviour that the locked file has since closed.

## DRAFT — Layer 1 sketch

The types and signatures below are a draft sketch. They are not a locked schema, not a database design, and not code. An identifier that the locked file does not name is omitted. Where a field would have to be invented to make a function compile, the item is in [Technical gaps](#technical-gaps) instead of in the sketch.

### Data the locks already name

```text
OrganisationId, PersonId          opaque strings. Enigma owns the records (§15).

FrozenIdentity                    captured at booking (§16)
  name
  id_number
  service_address
  Later Enigma edits do not write these three fields again.

ProviderCalcChoice                stored per organisation or per product
  interest_on_deferred_initiation bool
                                  unset means no (§10). This is a locked default,
                                  unlike the two choices below.
  repo_after_fall                 unset | contract_rate | lower_of_contract_and_statutory_max
                                  unset fails closed (§11). Option B also issues
                                  the section 104 notice. The notice is not a rate.
  day_count                       the provider's choice (§5)
                                  the two named methods are actual/actual and standard 30/360
                                  see the conflict in Technical gaps before coding a third
  fee_cap_basis                   exclusive | inclusive
                                  exclusive is the locked default (§9)

CustomerDefaultConfig             per customer (§6). Both fields required.
  leniency_days                   calendar days, including weekends and public holidays
  full_payment_threshold_percent  percent of the due-date instalment
                                  no numeric value is a platform default

Campaign                          stored and displayed, not collapsed to one rate (§3)
  base_rate                       x%, the contractual rate
  discount                        y%
  effective_rate                  x% − y% while the discount is on
                                  x% from the flag date onward
  The discount does not come back when the episode cures.

InitiationTreatment               §2
  capitalised                     part of principal. If capitalised before the
                                  default date, included in that episode's ceiling (§7).
  not_capitalised                 section 126 fee or charge

LaybyeLink                        parent/child, required when a hold exists (§4)
  parent_agreement_id
  child_laybye_id
  The pair is one loan. The hold is not security that makes the loan secured.
  One monthly service fee, levied on the parent.
  Structure named by §4: cash deposit, or insurance.
  Funeral beneficiary, when one is named.
  Section 124 authority signed in life, when one exists.
    Without it, death does not apply the lay-by. The lay-by stays with the estate.

DuplumEpisode                     §7
  started_on
  ceiling                         unpaid principal at that start, including
                                  pre-default capitalised initiation
  accrued                         charges that accrue during the episode
  closed_on                       set when a cure closes the episode
  A payment inside the episode reduces what is owed and does not reset accrued.
  The next default is a new episode with a new ceiling.
  Charges that caused the default are outside accrued.

TariffRow                         §18
  Absent row: fail closed. Do not substitute a rand amount.
  The locked file does not name the row's columns. See Technical gaps.

AdditionalMonthlyFee              §13 and §18
  fixed or variable
  not a principal-schedule amount
  The variable basis is not named. See Technical gaps.

DueDateBundle                     §6, used only for the threshold test
  due_on
  original_cents                  principal slice due that date
                                  + levied charges due that date
                                  (monthly service fee, non-capitalised initiation,
                                  credit life, once each has been levied)
  received_cents                  value-dated on or before the flag date,
                                  including 00:00 on the flag date
  Unbilled interest is not in original_cents.

PaymentFrequency                  §14
  weekly | fortnightly | monthly | quarterly | bi_annual | annual
  The locked file does not say how the next due date is generated.

StatementScope                    §12
  one statement per client, all loans
  The line layout is not named.

DisbursementTiming                §13, provider choice when disbursement is after the quote date
  adjust_instalment               actual disbursement date and remaining term
  keep_instalment                 original instalment; early settle, or a small
                                  residual write-off at contractual end
                                  write-off is not required if already in default

PrepaymentReshape                 §13, provider choice after a partial prepayment
  shorten_term | drop_instalment
  No platform default is stated. See Technical gaps.
  Preference, also in §6: keep the contractual instalment the same during the term.
  "Prefer" is not an algorithm.
```

### Draft function signatures

These signatures are the draft. Preconditions that are already locked are written as invariants under the signature. A signature is omitted where the locked file does not identify the inputs.

```text
flag_default(bundle, leniency_days, threshold_percent, on) -> flagged
  Precondition: leniency_days and threshold_percent are present.
  Missing either one fails closed. No substitute number.
  Flag date = bundle.due_on + leniency_days calendar days.
  flagged when received_cents / original_cents is below the threshold.
  Payments whose value date is the flag date are already inside received_cents.
  Same definition for in-duplum and for collections.

campaign_rate(campaign, on, discount_active) -> (base, discount, effective)
  Display stores base and discount even after fall-away.
  discount_active is true through the leniency window.
  discount_active becomes false on the flag date and stays false after a cure.
  effective is the base rate when discount_active is false.
  effective must not exceed the contractual base rate.
  A campaign whose result is 0% is base minus discount = 0%.

daily_interest(net_balance, effective_rate, day_count, on) -> amount
  Accrual is daily (§5).
  Leniency does not pause or reduce this amount.
  net_balance for a linked lay-by is loan principal minus lay-by hold (§4).
  Rounding to cents happens on billing, half-up (§17).

opening_service_fee(monthly_cap, inclusive_days, days_in_month) -> ex_vat
  Fraction = inclusive_days / days_in_month (§9).
  Later months, including the settlement month, use the full cap.
  Cap is ex-VAT unless the provider elected inclusive.
  One fee, on the parent, when a lay-by is linked.

duplum_ceiling(unpaid_principal, capitalised_initiation_already_in_principal) -> cents
  Read at the start of the episode.
  capitalised_initiation_already_in_principal is included only when it was
  capitalised before that date (§2, §7).
  A new episode reads the ceiling again. It does not reuse the previous ceiling
  and it does not subtract the previous episode's accrued total.

apply_section_126(amount, interest, fees, principal) -> allocation
  Order: due or unpaid interest, then due or unpaid fees or charges, then principal (§8).
  The locked file does not order items inside the fee class.

repo_rate(choice, contract_rate, statutory_max, on) -> rate
  choice unset: fail closed (§11). Do not return contract_rate or statutory_max.

tariff_charge(row) -> amount
  row missing: fail closed (§18).

death_application(credit_life, laybye, loan, s124_signed_in_life, structure, beneficiary) -> posting
  Credit life pays the loan first.
  Lay-by covers any shortfall only when s124_signed_in_life is present.
  Otherwise the lay-by is not applied and stays with the estate.
  Surplus of a cash-deposit lay-by goes to the estate.
  Insurance treatment follows whether a beneficiary was named.
  A funeral benefit pays the named beneficiary and does not change the loan
  or the lay-by (§4).
  No premium formula is implied by this signature.
```

## Invariants

These are the locked sentences, stated so a test can fail if code drifts. They are not new rules.

1. Value date is the system recognition date. Start of day is 00:00. A loan, settlement, or deposit on a calendar day is 00:00 that day. A reversal uses the original recognition date (§1).
2. A payment on a flag date is 00:00 that day and is visible to the morning default check (§1, §6).
3. Capitalised initiation is principal. Non-capitalised initiation is a section 126 charge. A capitalised initiation fee capitalised before the default date is inside that episode's ceiling (§2, §7).
4. Zero interest and zero fees calculate for a whole term or for part of a term. A 0% campaign is base minus discount = 0%. The stored display keeps x% and y% (§3).
5. The interest discount remains during leniency, drops on the flag date, and stays off after cure. The resulting rate is the base rate and is not above the contractual rate (§3).
6. A linked lay-by is a child of one parent loan, not security. Interest uses principal minus hold. One service fee is charged, on the parent (§4).
7. Consolidation or settlement is available when the lay-by balance is at least the settlement balance (§4). The settlement-balance formula is the section 125 quote already in the calculation contract. §4 does not define a second one.
8. Death follows the credit-life, shortfall, surplus, funeral, and section 124 order in §4.
9. Day-count is the provider's choice between actual/actual and standard 30/360. New products are recommended actual/actual. Accrual is daily (§5). The conflicting "360-day year is not required for Day-1" sentence is a gap, not an permission to drop 30/360 silently.
10. Default uses one definition. Leniency is calendar days. Unset leniency or threshold fails closed. The threshold instalment is the original principal slice plus levied charges that share the due date, including service fee, non-capitalised initiation, and credit life. Unbilled interest is excluded until debited (§6).
11. Interest accrues every day on the outstanding balance through leniency (§6).
12. In-duplum ceiling, non-reset on payment, cure closes the episode, and the next default gets a fresh ceiling (§7). Charges that caused the default are outside the cap. Post-default accruals count even if a statement capitalises them.
13. The three unnamed section 103(5) edges stay unclipped until counsel confirms (§7). No edge is switched off by guessing its name.
14. Section 126 order is interest, then fees or charges, then principal (§8).
15. Service fee: opening month only is pro-rata, by the §9 fraction; every later month including settlement is the full fee, capped at R60. Rand maxima are ex-VAT unless the provider elects inclusive (§9).
16. Deferred-initiation interest is off unless the stored provider choice says on (§10).
17. After a repo fall, no rate is produced until the stored choice is Option A or Option B (§11).
18. One statement per client for all loans (§12).
19. Subsequent short-term status is per credit-provider organisation (§13).
20. Partial prepayment uses the stored shorten-term or drop-instalment choice (§13). There is no locked substitute when the choice is missing.
21. Extra costs outside interest, initiation, monthly service, and credit life are an additional monthly fee, not capitalised principal (§13, §18).
22. Frequencies in §14 are all available.
23. Enigma timeout or ambiguous status fails closed. The LMS does not store a person or an organisation beyond the opaque ids, plus the three frozen identity fields (§15, §16).
24. Billing rounds half-up to cents. The same rounding rule is used wherever a round is required (§17).
25. A missing tariff row does not become a charge (§18).

## Technical gaps

Each gap is a missing name, a missing formula, or two locked sentences that cannot both be implemented as written. No repair is proposed.

| Id | Locked text | What is missing |
| --- | --- | --- |
| G-360 | §5 requires standard 30/360 and also says a 360-day year is not required for Day-1 | Standard 30/360 uses a 360-day year. An implementer cannot both offer 30/360 and omit a 360-day year without dropping one sentence. |
| G-CLIP | §7: three section 103(5) edges not decided by Nedbank stay unsigned, and the clip stays off until counsel confirms | The three edges are not named. "The clip" is not tied to a charge type. Turning every clip off would also drop the ceiling rule in the same section. Turning none off would ignore the sentence. Neither reading is chosen here. |
| G-PRORATA | §9: opening month is "disbursement to first payment due", and the fraction is "inclusive days in the month / actual days in that month" | "Inclusive days in the month" has no start date and no end date. A first payment due in a later calendar month does not fit one month's denominator. |
| G-HOLD-POST | §4: interest is principal minus hold, and that net figure is evidence the hold is a payment against the loan | A section 126 payment reduces interest, then fees, then principal. An interest-base offset does not. The ceiling is unpaid principal (§7). The file does not say whether the hold reduces that principal. |
| G-HOLD-DAY | §1 values a deposit at 00:00 on its calendar day. The existing interest convention excludes same-day receipts from that day's base | If the hold is a deposit or a payment, §1 puts it in the day's opening balance. The file does not say the interest convention survives that. |
| G-HOLD-GT | §4 states a net balance and does not mention a negative base | A hold larger than principal has no locked result. The calculator floors the interest base at zero. That floor is not a locked sentence. |
| G-FEE-FALL | §3 locks fall-away for the interest rate. It also requires fees of R0 to calculate | It does not say a fee discount ends on the flag date, and it does not say fee discounts are a percentage rather than an amount. |
| G-DISCOUNT-GT | §3: a campaign that sets the rate to 0% is base minus discount = 0% | A discount larger than the base is not described. A negative rate is not a locked output. |
| G-REPO-STORE | §11 fails closed until the provider chooses | The storage key is "per organisation or per product". Which of the two wins when both are present is not said. The section 104 notice has no template in this repository. |
| G-PREPAY | §13 requires the provider's shorten-term or drop-instalment choice and does not say "fail closed" | There is no locked behaviour for a missing choice. "Prefer keeping the contractual instalment the same" does not select one of the two options. The disbursement-timing options in the same section can also move the instalment. |
| G-AER | §17 requires disclosure of the annual equivalent rate | No conversion from the monthly short-term rate or from repo-plus-margin is given. |
| G-ROUND-CAP | §17: a round must not create a compliance issue, for example an instalment rounded above the affordability figure already aligned with the client | The affordability figure's source field, and the operation when the round would cross it, are not named. |
| G-CREDITLIFE | §6 puts levied credit life in the threshold instalment and in affordability. §4 states the death order | No premium, no frequency inside the instalment, and no section 106 cover test are given. |
| G-TARIFF-COLS | §18 fails closed until a tariff row exists | The columns of the row are not named. Regulation 46 and regulation 47 still do not state a rand amount in this repository. |
| G-VAR-FEE | §13: additional monthly fee, fixed or variable | The variable amount's inputs are not named. |
| G-RESTRUCTURE | §13: restructuring creates a new instalment, pricing, and term | Whether the old episode, campaign, frozen identity, and lay-by link move to the new term is not said. |
| G-RELATED-FEES | §2: the capitalised / not-capitalised split applies to "related fee points" | Those fees are not listed. |
| G-S102 | §2 allows capitalised initiation to be principal. Section 102 of the Act is the restriction this contract already cites for unsecured and short-term agreements | The two texts are not reconciled here. |
| G-DUE | Non-capitalised initiation still has no locked due date | D-INIT-DUE remains the calculator's behaviour only. |
| G-FEE-ORDER | §8 orders fees as one class | The order inside the class is not locked. The calculator's rank is not promoted by this checklist. |
| G-FREQ | §14 names six frequencies | The rule that turns a frequency into the next due date is not stated. |
| G-STMT | §12: one statement per client, all loans | Which balances, which date, and whether the lay-by child is its own line are not stated. |
| G-FREEZE | §16 freezes name, ID number, and service address | What happens when the booking payload omits one of the three is not stated. §15 already fails closed on an ambiguous Enigma status. |
| G-REVERSE | §1: a reversal reuses the original value date | The order in which a reversal rebuilds a duplum episode, a campaign that has fallen away, and a cured flag is not stated. |
| G-SETTLE-BAL | §4: settle when lay-by ≥ settlement balance | "Settlement balance" is not given a second formula. The section 125 total is the only settlement total already specified. Using it is a reference, not a new rule. Whether the comparison is before or after the section 113 window is not said. |
| G-INS-BEN | §4: if structured as insurance, treatment follows whether a beneficiary was named | The result when a beneficiary was named, other than the funeral sentence, is not spelled out. The funeral sentence itself is locked and is not this gap. |

## Calculator divergence

`src/lms/calc/` was not edited for this checklist. These are the places it does not yet meet an invariant above.

| Invariant | What the calculator does now |
| --- | --- |
| Flag-date payment is visible to the morning check | The fold tests default before it applies payments dated that day. A payment on the flag date can close the episode later the same day. It does not stop the episode from opening. |
| Unset leniency or threshold fails closed | `Policy` constructs with `leniency_days = 1` and threshold 100. |
| Repo choice fails closed | Personal interest is always `repo(day) + margin`. There is no stored Option A or Option B. |
| Prepayment is the provider's shorten-term or drop-instalment choice | Principal reduces the earliest unpaid slice. |
| Ceiling includes pre-default capitalised initiation | Initiation is always a section 126 fee. The ceiling is cash principal. |
| Full service fee in the settlement month | `terminal_service_fee = pro_rata` is still selectable and produces a smaller fee. The default setting of that switch matches the lock. |
| Standard 30/360 is available | `DayCount.FIXED` divides a personal year by 365, including in a leap year. |
| Missing tariff row fails closed | A caller can pass a default-administration or collection total. |
| Death, funeral, consolidation, credit-life premium | Not posted. `guard_s124` only checks an amount and dates the caller already extracted from a mandate. |
| Annual equivalent disclosure, one statement per client, six frequencies, frozen identity, reversals, external decision engine | Not in this package. |

Examples 11 and 13 remain valid pins of the current fold. They pass leniency in as an argument. They do not show a flag-date payment, and they do not show a missing leniency configuration failing closed.

## Not newly locked

These older open items were not closed on 27 October 2026. Building the checklist must not fill them in.

- D-VAT-TIME: which VAT rate applies inside a month when the rate changes. The calculator uses the levy date for the whole fee.
- D-INIT-DUE: due date of a deferred non-capitalised initiation fee.
- D-ALLOC: order inside the fee class.
- D-VAT-DUPLUM: whether VAT consumes the ceiling. Not identified with G-CLIP.
- D-THRESHOLD: the rand thresholds still cited from GN 713 of 2006 and regulation 39(2).
- D-LARGE: the section 125(2)(c) three-month charge. Day-1 still rejects a personal loan at or above R250,000.
- D-BNPL: a later fee on a zero-cost plan, and the incidental-credit cap.
- D-HOLD-INTEREST: CPA interest on a goods lay-by. §4 is about a lay-by linked to a loan, which is a different product.
