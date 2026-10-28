# External Decision Engine Intake

**Status: Layer 2 draft.** Design only. This note is not production code, not a schema migration, and not a locked decision. It does not change `docs/LOCKED_DECISIONS.md`. Where this note and that file disagree, that file wins.

Date: 28 October 2026 (Africa/Johannesburg). Source of truth: `docs/LOCKED_DECISIONS.md`, last updated 28 October 2026.

Layer 0 (configuration, calculation engine, ledger, servicing) and Layer 1 (collections, Laybye, statements, regulatory extracts) are already implemented. This layer calls those interfaces. It does not re-implement interest, fee caps, election resolution, identity, allocation, or journals. `main` does not contain that code. The symbols below are the public surfaces on the Layer 0 and Layer 1 implementation branches.

A later implementation follows the call sequence in this note and stops where section 9 says the lock is silent. It does not fill those gaps.

## 1. What this layer owns

Intake is the boundary in front of `Servicing.book` and `Servicing.disburse`. A decision engine, either the platform engine or an external engine, submits a quote the client has accepted. Intake checks that quote against the stored elections and the NCA caps, then hands the principal schedule to servicing.

Intake does not price the contractual instalment. The day-1 calculation engine does not originate credit. `lms.calc.ledger.run` accrues a position it is given. It has no function that turns principal, rate, and term into a contractual instalment. Servicing states the same limit: a schedule is required, and servicing does not build one.

| This draft | Left where it already lives |
| --- | --- |
| Which engine may submit a quote, and the payload that quote must carry | Affordability assessment (NCA s 81), the quotation document (s 92), and the agreement form (s 93) stay in origination |
| Fail closed when a required election, cap row, or method stamp is missing or inconsistent | `resolve_customer_settings`, `resolve_charge`, and `Agreement` construction |
| Record which late-disbursement option applies, and refuse to rewrite an accepted instalment with a different method | `Ledger.grant` already stamps `adjust_instalment` or `keep_instalment` and keeps the caller's principal lines |
| Ask the same engine for an option-(a) re-quote | The arithmetic of that re-quote |

Decision 13 allows the platform engine to be forced at first, and requires the LMS to accept an external engine after that. The contractual instalment the client has accepted is binding when the quote date and the disbursement date differ. The provider's stored choice (decision 19) selects which of the two late-disbursement options runs. The preference in decision 13 for keeping the instalment unchanged during the term is not written in when the stored choice is `adjust_instalment`.

## 2. Interfaces this draft calls

Configuration, from `lms_config`:

| Call | Use |
| --- | --- |
| `PUBLISHED_TERMS_SQL`, `CUSTOMER_SETTINGS_SQL`, `INTEREST_CAP_SQL`, `REFERENCE_RATE_SQL`, `SHORT_TERM_ORDINAL_SQL`, `TARIFF_SQL` | One `REPEATABLE READ` read, in `ENGINE_READ_STEPS` order. No Enigma call on this read |
| `validate_terms` | The published product is a publishable Day-1 product. Day-1 initiation stays non-capitalised |
| `resolve_customer_settings` | Organisation election, product override. Unset fails closed for the elections that resolver already rejects |
| `resolve_in_duplum_trigger` | Decision 19. Unset fails closed. Called in addition to `resolve_customer_settings`, which still stores `None` |
| `resolve_residual_threshold_cents` | Decision 8's R50 when both levels are null. Intake does not apply a second default |
| `campaign_rate` | Effective rate is base minus discount, and may be zero. Compared with the payload. Not recomputed by subtraction in this layer |
| `require_reference_for_posting` | Missing interest-cap row, missing confirmed repo rate when the cap or the contract is repo-linked, or missing tariff row when a tariff charge is submitted |
| `nominal_annual_rate` | Decision 17 disclosure check, and only with a period count the lock already fixes (section 6) |
| `value_date` | Johannesburg civil date of a timezone-aware recognition timestamp. Decision 1 |

Calculation engine, from `lms.calc`:

| Call | Use |
| --- | --- |
| `initiation_cap_ex_vat_cents` and `initiation_fee` | Table B and the 15 percent limb. VAT basis comes from the resolved `vat_on_rand_maxima` |
| `service_fee_cents` with `Policy` | Monthly service fee cannot exceed the R60 cap. The opening-month fraction is `opening_service_fraction` (decision 9). Intake does not accept a caller-supplied fraction in its place |
| `micro_monthly_rate` | 5 percent or 3 percent cap. Priors are disbursed short-term loans only |
| `personal_annual_rate` | Contract rate and the decision 11 choice. Repo-fall tokens are the configuration tokens, mapped with the existing `lms.ledger.service._repo_fall` before this call |
| `Agreement(...)` | Regulation 39(2) amount and six-month term, margin at most 21 points, agreed rate at or under the cap, principal slices sum to the cash advanced. This is the same construction `Servicing._engine_validate` already performs |
| `periods_per_year` | 12 for a micro agreement, 1 for a personal agreement. It ignores payment frequency |
| `to_cents` | Half-up to cents on billing (decision 17). Daily interest stays at 10 decimal places until it is debited (`quantize_interest` inside `daily_interest_rands`) |

`daily_interest_rands`, `accrual_weight`, `divisor_days`, and `opening_service_fraction` are named in the method stamp (section 5). Intake does not call them to produce a replacement instalment.

Servicing, from `lms.servicing`:

| Call | Use |
| --- | --- |
| `Servicing.book` | Freeze elections, check Enigma mandate `agreement.book`, run `_engine_validate`, leave the agreement `pending_disbursement`. No ledger post |
| `Servicing.disburse` | Mandate `disbursement.confirm`, validate again on the actual advance date, then `Ledger.book` or `grant_loan` |

`dispatch` on `POST /v1/agreements` is not the intake path. That route builds only the two Day-1 templates (`micro_short_term`, `unsecured_personal`) and does not load published `cfg_product_terms`, so a product override would be invisible. Intake passes the `ProductTerms` from the configuration read into `Servicing.book`.

Later, and not at booking:

| Call | Use |
| --- | --- |
| `lms.calc.ledger.quote_settlement` | Existing section 113 / 125 settlement quote. Named here because option (b) can end in an early settlement. Intake does not call it while booking |
| `Collections.propose_residual_write_off` | Decision 8 residual, after contractual end, and only when a caller invokes it. Option (b) does not post this at disbursement |

Identity is `EnigmaStub.check` inside `Servicing.book` and `Servicing.disburse` (decision 15). Timeout, an ambiguous status, or a suspended enrolment fails closed. Name, identity number, and service address freeze at booking (decision 16). Intake does not read or store a person. The NCR registration number is the LMS organisation attribute (decision 21). Intake does not ask Enigma for it. A blank NCR number does not block booking.

`AgreementPin` in `lms_config.context` still says the NCR number is copied from Enigma at origination. That comment conflicts with decision 21. This draft follows decision 21.

## 3. Intake boundary

### 3.1 Forcing the platform engine

Decision 13 says the platform's own engine can be forced. The lock does not say where that switch is stored, who may change it, or what an unset switch means. It is not a decision 19 election.

Until that is locked, intake stops before any configuration read when the switch is absent. It does not treat absence as "forced" and it does not treat absence as "external allowed".

When a future lock says the switch is on, `source` must be `platform`. An external payload is rejected. When that lock says the switch is off, both `platform` and `external` are accepted and then run through the same checks. The platform engine is not `lms.calc`. No Layer 0 or Layer 1 module prices a contractual instalment. Forcing the platform engine means refusing every other source. It does not mean this layer calculates the quote.

### 3.2 External engine

An external payload uses the same fields, the same election check, and the same cap check as a platform payload. The external engine does not write `cfg_organisation_settings` or `cfg_product_terms`. Stored elections stay the provider's. A payload that repeats them is checked against the resolved row. A mismatch fails closed. Intake does not pick the payload over the store, or the store over a conflicting payload, by rewriting either one.

The caller still needs an Enigma mandate `agreement.book` for the organisation, because that is the check `Servicing.book` already makes. The lock does not define a separate external-engine principal.

### 3.3 The accepted instalment

The number the client accepted is the contractual instalment (decision 13). Intake stores that number on the intake pin and passes principal slices, not that number, through `Servicing.book`. The two figures are different. Section 9 records that Layer 0 has nowhere to put the contractual instalment.

After acceptance, intake does not ask the calculation engine to replace that number with a figure built by another method (decision 5 and decision 13).

## 4. Quote date and disbursement date

Dates are Johannesburg civil dates. A disbursement timestamp must carry a timezone, as `Servicing` already requires. The disbursement date is `value_date` of that timestamp (decision 1): the calendar day, treated as 00:00.

Decision 13 compares the disbursement date with the **quote date**. `Ledger.grant` compares the disbursement value date with **`quoted_disbursement`**, and when the value date is later it records the stored choice and keeps the caller's lines. It does not calculate a new instalment. The lock does not say the quote date and `quoted_disbursement` are the same day. A quote can be issued on one day for a disbursement on a later day.

This draft therefore requires `quote_date`. `quoted_disbursement` may be omitted or equal to `quote_date`. When they differ, intake fails closed and does not call `Servicing.book`. When they are the same, or only `quote_date` is present, that date is passed as `quoted_disbursement` so the ledger comparison matches decision 13.

| Disbursement value date against `quote_date` | What intake does |
| --- | --- |
| Earlier | Fail closed. Decision 13 states the later case only |
| Same civil day | Not a late disbursement. Book the accepted instalment and the accepted principal schedule |
| Later | Apply the resolved `late_disbursement` value. Unset has already failed in `resolve_customer_settings` |

### 4.1 Option (a) — `adjust_instalment`

The stored tokens are `lms_config.locked.LATE_DISBURSEMENT_ADJUST` (`adjust_instalment`) and `LATE_DISBURSEMENT_KEEP` (`keep_instalment`).

Option (a) adjusts the instalment from the actual disbursement date and the remaining term (decision 13). The LMS does not perform that adjustment. The same source that produced the original quote (`platform` or `external`) re-quotes, with:

- the same method stamp (section 5)
- the same principal, rate, fees, frequency, and elections
- the actual disbursement value date
- the original `first_due_date`, schedule dates, and `maturity_date`

"Remaining term" is the lock's phrase. The lock does not say whether due dates move, whether contractual end moves, or whether only the payment amount changes. Intake does not define it. The re-quoting engine receives the original dates and the actual disbursement date and returns a new payload. That payload is validated again from section 6. The principal total must be unchanged. Slices must still sum to the cash advanced. A capitalised initiation fee is not available on a Day-1 product (`validate_terms` rejects `initiation_capitalised`).

Decision 13 also says the instalment the client accepted is binding. The lock does not say that a stored `adjust_instalment` election is the client's acceptance of whatever number comes back later. This draft books the re-quoted instalment only when `accepted_instalment_cents` on that submission equals the re-quoted contractual instalment. If the only acceptance on file is the original number, intake stops. It does not disburse the original number under this election, because that would apply option (b). It does not disburse the new number without an acceptance of that number.

`Servicing.disburse` is called with the re-quoted principal schedule only after that acceptance check passes. `Ledger.grant` will keep those lines and stamp `reason = late_disbursement`. The new instalment has to be produced before that call. The ledger will not derive it.

### 4.2 Option (b) — `keep_instalment`

The accepted contractual instalment and the accepted principal schedule are passed through unchanged. `Servicing.disburse` posts them. A later accrual uses the pinned day-count, the pinned rate, and `daily_interest_rands`. Nothing in intake recomputes the payment amount because the dates differ.

Decision 13 then allows either an early settlement or a small residual write-off at contractual end.

- Early settlement, when the client later asks to settle, is `quote_settlement` (and `execute_settlement` when the payment is inside the binding window). That quote is the section 125 amount outstanding on the quote date. The lock does not say option (b)'s "settle early" means that quote, rather than continuing to take the original instalment until the balance clears. Intake does not add a second settlement formula. Using `quote_settlement` as the definition of this sentence is open (section 9).
- The residual write-off is `Collections.propose_residual_write_off`. Decision 8 says it is not automatic, and the threshold is the resolved client threshold (R50 when both levels are null). Intake does not call it at disbursement. The current command also refuses while an in-duplum episode is open. Decision 8 does not say that. This draft does not adopt that gate as a locked rule.

If the client pays a different amount from the contractual instalment, the difference is arrears (decision 8). Intake does not write that difference off.

### 4.3 Cap and term checked again at disbursement

`Servicing.disburse` calls `_engine_validate` with the actual advance date. `Agreement` then applies the short-term six-month limit from that date, and the 5 percent or 3 percent cap from disbursed priors on that date. A quote that was lawful on the quote date can fail on the disbursement date if the delay pushes maturity past six months, or if another short-term loan for the same organisation and person has disbursed in the same calendar year (decision 13: a subsequent loan is per organisation and per calendar year; a quote that never disburses does not count).

Intake does not reclassify a failed short-term agreement as unsecured. Servicing already refuses to switch classification inside the product. The engine error stands. Whether the provider must refuse the loan or obtain a new accepted quote inside the cap is open (section 9). An unlawful rate is not booked in order to keep the original instalment.

## 5. Payload

Amounts are integer cents, currency `ZAR`. Rates are decimals (`0.05` is 5 percent per month, not 5 and not 0.05 percent). Dates are `YYYY-MM-DD`. Timestamps carry a timezone. Identifiers are opaque strings. The sample below is the shape, not a worked price. This draft does not calculate the instalment figure in it.

### 5.1 Minimum fields

The engine must supply every field in this table. A missing field fails closed. Zero is a value and must be sent as zero. It is not the meaning of an omitted field.

| Field | Constraint |
| --- | --- |
| `source` | `platform` or `external` |
| `decision_reference` | Engine's id for this quote. Copied onto the intake pin. Not an Enigma id |
| `idempotency_key` | Passed to `Servicing.book`. A replay of the same key and the same body returns the original agreement. The same key with a different body is the servicing 409 |
| `organisation_id`, `person_id` | Opaque. Enigma owns the records |
| `product_code` | A published product for that organisation. Terms come from `PUBLISHED_TERMS_SQL`, not from the payload's price |
| `classification` | Must equal the published terms. `short_term`, `unsecured`, `zero_cost`, `cpa_layby`, or `incidental` |
| `principal_cents` | Positive cash advanced |
| `rate.base_rate`, `rate.discount_rate` | Decision 3 pair. Effective rate is `campaign_rate`, which may be zero. The period is `month` for `short_term` and `year` for `unsecured`, matching `periodic_rate` |
| `rate.effective_rate` | Must equal `campaign_rate(base, discount)` while the campaign still applies. Intake uses that function for the comparison |
| `term.quote_date` | Civil date of the quote. Decision 13's comparison date |
| `term.quoted_disbursement` | Omitted, or equal to `quote_date`. A different day fails closed (section 4) |
| `term.first_due_date`, `term.maturity_date` | `maturity_date` is the contractual end passed to the ledger |
| `term.payment_frequency` | One of `weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual` (decision 14) |
| `term.principal_schedule` | `{due_on, principal_cents}` lines. Sum to `principal_cents`. These are principal slices, not the contractual instalment. `Servicing.book` already requires them |
| `contractual_instalment_cents` | The payment the client accepted (decision 13). Positive, or zero only when `validate_terms` has accepted a zero-cost product |
| `acceptance.accepted_on`, `acceptance.accepted_instalment_cents` | `accepted_instalment_cents` must equal `contractual_instalment_cents` on a booking submission |
| `fees.initiation_fee_cents` | Zero or more. Checked against `initiation_cap_ex_vat_cents`. Not added to the schedule on a Day-1 product |
| `fees.monthly_service_fee_cents` | Zero or more, and not above the R60 cap. Decision 9, not the caller, fixes the opening-month fraction |
| `elections` | Section 5.2. Every listed election is present |
| `calculation_method` | Section 5.3. Every listed token is present |

`credit_life_premium_cents` is required when the payload says credit life is sold, and forbidden from the principal schedule. Decision 4 keeps the premium as a separate collection. The LMS does not calculate it and does not keep a credit-life account. When credit life is not sold the field is JSON `null`, not an omitted key. An omitted key fails closed. A single instalment figure that blends the premium into `contractual_instalment_cents` fails closed, because decision 4 and decision 6 cannot both be applied to an undifferentiated number. Decision 6 adds the premium into the affordability instalment. It does not add the premium into the ledger principal.

`additional_monthly_fees` is an array, possibly empty. Each entry is a further monthly fee, fixed or variable (decision 13). It is not added to `principal_schedule`. A variable fee with no amount fails closed. The fee-code list is not locked (section 9). An entry whose code is default administration or collection cost is a tariff charge: `require_reference_for_posting` with `tariff_required` true. The Day-1 tariff table is empty, so that charge fails closed (decision 18).

`affordability_instalment_cents` may be present. When it is present, `contractual_instalment_cents + credit_life_premium_cents` (premium treated as 0 when credit life is null) must be less than or equal to it (decision 6 and decision 17). When it is absent, intake does not invent a pass and does not invent a failure. The booking consequence of a missing figure is open (section 9).

A payload NCR number, if present, must equal the LMS organisation attribute. Intake does not write the attribute from the payload. A blank LMS attribute does not block booking (decision 21).

### 5.2 Elections

The payload repeats the elections the quote used. Intake resolves the store and compares. The store is `resolve_customer_settings`, `resolve_in_duplum_trigger`, and `resolve_residual_threshold_cents`.

| Payload field | Store | Fail closed when |
| --- | --- | --- |
| `vat_on_rand_maxima` | `exclusive` or `inclusive` | Missing, unknown, or different from the resolved value |
| `late_disbursement` | `adjust_instalment` or `keep_instalment` | Missing, unknown, or different |
| `partial_prepayment` | `shorten_term` or `drop_instalment` | Missing, unknown, or different. Not applied at intake. A later prepayment uses the snapshot servicing already copies |
| `interest_on_deferred_initiation` | `none` or `permitted` | Missing, unknown, or different. The word `none` has to be stored. Null is not filled in |
| `repo_rate_fall` | `contract_rate` or `lower_of_contract_and_cap` | Missing, unknown, or different. Required by the current resolver even for a monthly short-term cap that is not repo-linked |
| `in_duplum_trigger` | `contractual_breach` or `collections_default` | Missing or different. `resolve_in_duplum_trigger` rejects an unset value. `ElectionSnapshot` does not currently copy it |
| `residual_write_off_threshold_cents` | Resolved cents, including 5000 when both levels are null | Different from `resolve_residual_threshold_cents`. The payload sends the resolved cents, not a second default |
| `day_count` | `actual_actual` or `thirty_360` | Missing, `fixed`, or different. `DayCount.FIXED` (30/365) is not a decision 5 choice |
| `base_rate`, `discount_rate` | The resolved campaign pair | Different. A zero-cost or CPA lay-by product resolves to zeros inside `resolve_customer_settings` |

Leniency and the full-payment threshold are resolved by the same call and copied by servicing. They do not change the contractual instalment. They are not extra payload prices. An unset value still fails inside `resolve_customer_settings` (decision 6).

### 5.3 Method stamp

Decision 5 and decision 13: accrual uses the same day-count and the same base method as the contractual instalment. The stamp is how intake checks that without calculating a new instalment. Each token names the method Layer 0 already implements. Any other token fails closed.

| Field | Required token | Existing behaviour it names |
| --- | --- | --- |
| `day_count` | The resolved `actual_actual` or `thirty_360` | `accrual_weight` and `divisor_days` |
| `accrual` | `daily` | Decision 5. Accrual frequency is daily |
| `interest_formula` | `reg40_daily` | `daily_interest_rands`: deferred amount × periodic rate / divisor × weight. Unbilled at 10 dp. Half-up to cents when debited |
| `interest_base` | `interest_bearing_cents` | Principal, minus a deferred initiation fee unless the election is `permitted`, minus a Laybye hold. The hold does not reduce principal for in-duplum or settlement (decision 4 and decision 10) |
| `service_fee_opening` | `decision_9_inclusive_days` | `opening_service_fraction` |
| `service_fee_thereafter` | `full_month_capped` | Full monthly fee, including the settlement month, subject to the cap (decision 9) |
| `rounding` | `half_up_cents_on_billing` | `to_cents` |
| `campaign` | `base_minus_discount` | `campaign_rate`. The discount falls away on the default flag date and does not return |

A regulation 40(4) method that is allowed to differ by up to 0.1 percent over a year is not one of these tokens. The day-1 engine uses the prescribed daily method. The lock does not store a third method. A stamp that names any other formula fails closed.

### 5.4 Illustrative shape

```json
{
  "source": "external",
  "decision_reference": "dec_01J0",
  "idempotency_key": "book_01J0",
  "organisation_id": "org_01J0",
  "person_id": "per_01J0",
  "product_code": "short_term_v1",
  "classification": "short_term",
  "principal_cents": 500000,
  "rate": {
    "period": "month",
    "base_rate": "0.05",
    "discount_rate": "0",
    "effective_rate": "0.05"
  },
  "term": {
    "quote_date": "2026-10-26",
    "quoted_disbursement": "2026-10-26",
    "first_due_date": "2026-11-25",
    "maturity_date": "2026-11-25",
    "payment_frequency": "monthly",
    "principal_schedule": [
      { "due_on": "2026-11-25", "principal_cents": 500000 }
    ]
  },
  "contractual_instalment_cents": 583150,
  "acceptance": {
    "accepted_on": "2026-10-26",
    "accepted_instalment_cents": 583150
  },
  "fees": {
    "initiation_fee_cents": 56500,
    "monthly_service_fee_cents": 6000
  },
  "credit_life_premium_cents": null,
  "additional_monthly_fees": [],
  "elections": {
    "vat_on_rand_maxima": "exclusive",
    "late_disbursement": "keep_instalment",
    "partial_prepayment": "shorten_term",
    "interest_on_deferred_initiation": "none",
    "repo_rate_fall": "contract_rate",
    "in_duplum_trigger": "collections_default",
    "residual_write_off_threshold_cents": 5000,
    "day_count": "actual_actual",
    "base_rate": "0.05",
    "discount_rate": "0"
  },
  "calculation_method": {
    "day_count": "actual_actual",
    "accrual": "daily",
    "interest_formula": "reg40_daily",
    "interest_base": "interest_bearing_cents",
    "service_fee_opening": "decision_9_inclusive_days",
    "service_fee_thereafter": "full_month_capped",
    "rounding": "half_up_cents_on_billing",
    "campaign": "base_minus_discount"
  }
}
```

`583150` is only an illustration of the field. It is not a result from `lms.calc`.

## 6. Validation before booking

Order is fixed. A failure stops the sequence. Later steps are not used to "correct" an earlier failure.

1. **Shape.** Every section 5.1 field is present. `source` is a known token. Frequency is one of the six. Schedule lines are positive. `accepted_instalment_cents` equals `contractual_instalment_cents`. Credit life is either `null` or a non-negative premium excluded from the schedule. `quote_date` and `quoted_disbursement` do not disagree.
2. **Force switch.** If the switch is unset, stop (section 3.1). If it is on, `source` is `platform`.
3. **Configuration read.** `REPEATABLE READ`. No Enigma. Steps follow `ENGINE_READ_STEPS` for the rows this quote needs:
   - published terms (`PUBLISHED_TERMS_SQL`)
   - `validate_terms`
   - customer settings (`CUSTOMER_SETTINGS_SQL`, then `resolve_customer_settings`)
   - `resolve_in_duplum_trigger`
   - `resolve_residual_threshold_cents`
   - interest cap (`INTEREST_CAP_SQL`)
   - confirmed repo (`REFERENCE_RATE_SQL`) when the classification or the contract is repo-linked
   - `require_reference_for_posting`
   - tariff row only when a submitted fee is default administration or collection
   A missing published term, a missing required election, a missing cap row, or a missing confirmed repo rate fails closed. `SHORT_TERM_ORDINAL_SQL` counts disbursed agreements only. Intake does not pass an undisbursed quote into that count.
4. **Elections and method.** Compare section 5.2 and section 5.3 to the resolved values. Any difference fails closed. `campaign_rate` must equal `rate.effective_rate`.
5. **Caps, by the calculation engine.**
   - Initiation: `fees.initiation_fee_cents` is the amount passed to `Servicing.book`. That method rejects it when it is greater than `initiation_cap_ex_vat_cents`. Intake uses that comparison and does not gross the fee up. `initiation_fee` is the consumer total under the resolved VAT basis. The book path does not call it. When a quote discloses a consumer total, that total has to equal `initiation_fee`. A disagreement fails closed. See gap 26.
   - Service fee: `service_fee_cents` rejects a monthly amount above R60. The opening fraction is not taken from the payload.
   - Rate and term: `micro_monthly_rate` or `personal_annual_rate`, then `Agreement` with the principal schedule, the advance date used for this check, and disbursed priors only. Above-cap rates, a short-term advance above R8 000, a short-term term beyond six months, a personal margin above 21 points, and a personal advance at the large-agreement line fail inside that constructor.
   - Disclosure: for a monthly short-term rate, `nominal_annual_rate(periodic, periods_per_year(Product.MICRO))` which is the monthly rate times 12. For an unsecured annual rate, `periods_per_year` returns 1, so the disclosed annual figure is that rate. Any other frequency fails this check closed. Decision 17 does not say whether weekly means 52 or 365/7, and this draft does not choose.
6. **Affordability figure, when present.** Reject when the contractual instalment plus the credit-life premium exceeds it (decision 17). Rounding stays half-up. Intake does not round the accepted instalment onto the affordability figure.
7. **Book.** `Servicing.book` with the published `ProductTerms`, the organisation settings, the principal schedule, `initiation_fee_cents`, the frequency, the cash advanced, `quoted_disbursement` set to `quote_date`, and the idempotency key. Servicing checks Enigma, resolves elections again, and runs `_engine_validate`. Intake does not copy engine amounts onto the ledger. Status is `pending_disbursement`.

The contractual instalment, the method stamp, `source`, `decision_reference`, and `quote_date` are intake pin fields. `AgreementRecord` and `ElectionSnapshot` do not store them today. Section 9 says a column set is not authorised by this draft. `Servicing.book`'s idempotency fingerprint hashes the schedule, the cash advanced, the frequency, the initiation fee, `quoted_disbursement`, the recognition timestamp, and the classification. It does not hash the contractual instalment. A later implementation that adds the pin has to include that number in the fingerprint. Otherwise a replay can confirm a different accepted instalment.

### 6.1 Disbursement

1. `value_date` of the disbursement timestamp.
2. Earlier than `quote_date`: fail closed.
3. Same day: `Servicing.disburse`. The original schedule is the schedule.
4. Later, and the resolved choice is `keep_instalment`: `Servicing.disburse` with the original schedule and the original accepted instalment. No write-off.
5. Later, and the resolved choice is `adjust_instalment`: return a re-quote request to the same `source`. Do not call `daily_interest_rands` or `run` to build the new payment. On the returned payload, repeat section 6 from step 1. Call `Servicing.disburse` only when the new `accepted_instalment_cents` equals the new `contractual_instalment_cents` and the principal total is unchanged. Otherwise stop.
6. `Servicing.disburse` validates on the actual advance date and posts through the ledger. `Ledger.grant` stamps `late_disbursement` when `quoted_disbursement` is earlier than the value date, and it keeps the lines it was given.

Accrual after disbursement stays on the ledger: `accrue_day` uses the pinned day-count and `daily_interest_rands`. That is the method the stamp required. Servicing does not ask the external engine to accrue.

## 7. Call sequence

```text
intake.accept(payload)
  require payload fields                         (this layer, shape only)
  stop if the force switch is unset              (gap; no booking)
  lms_config.context SQL, REPEATABLE READ
  validate_terms(product)
  resolve_customer_settings(organisation, product)
  resolve_in_duplum_trigger(...)
  resolve_residual_threshold_cents(...)
  require_reference_for_posting(...)
  campaign_rate(...)                             compare to payload
  nominal_annual_rate(...)                       only for the fixed period counts
  initiation_cap_ex_vat_cents(...)
  service_fee_cents(...)                         monthly cap
  micro_monthly_rate(...) or personal_annual_rate(...)
  Agreement(...)                                 regulation 39, rate, schedule sum
  Servicing.book(...)                            Enigma agreement.book, _engine_validate
                                                 no ledger post

intake.disburse(agreement, recognised_at)
  value_date(recognised_at)
  same day or keep_instalment:
      Servicing.disburse(...)                    Enigma disbursement.confirm
                                                 _engine_validate on the actual advance
                                                 Ledger.book / grant_loan
  adjust_instalment and the day is later:
      same engine re-quotes                      not lms.calc
      intake.accept(new payload)                 acceptance must match the new instalment
      Servicing.disburse(...)                    lines are the re-quoted principal schedule

later, not intake:
  quote_settlement(...)                          client asks to settle
  Collections.propose_residual_write_off(...)    caller invokes it after contractual end
```

Partial prepayment (`shorten_term` or `drop_instalment`) is stored and checked at intake and applied later by the ledger's existing `allocate_payment` path. Restructuring (decision 13) is not an intake of a new external quote. Whether a restructure is a new agreement or an amendment of the frozen pin is already open, and this draft does not close it.

## 8. One method for the quote and for accrual

The contractual instalment is accepted as a number. Accrual does not rebuild it.

The method that number was built with has to be the method accrual will use:

- Day-count is the resolved `actual_actual` or `thirty_360`, including the 30/360 weights `accrual_weight` already implements.
- Accrual is daily.
- The interest base is `interest_bearing_cents`.
- The rate is `campaign_rate` of the pinned base and discount, then the statutory cap through `resolve_charge` / `Agreement` on the origination date. A campaign base that would exceed the cap once the discount falls away already fails on that date inside `resolve_charge`.
- Fees use `initiation_fee` and `service_fee_cents` with `opening_service_fraction` in the opening month.
- Billing rounds with `to_cents`.

If the stamp does not name that set, the quote is rejected. After acceptance, a second call that would replace the instalment using a different day-count, a different base, a monthly annuity, or a regulation 40(4) alternative is not made.

Option (a) is a new quote by the same engine under that same stamp, followed by a new acceptance, followed by disbursement of the new principal schedule. It is not an accrual-time correction.

## 9. Gaps that still need a locked decision

These are raised. This draft does not close them and does not implement around them.

1. **Force switch.** Decision 13 allows the platform engine to be forced. It does not say where the switch lives, who sets it, or what an unset switch means. It is not in the decision 19 list. This draft books nothing while the switch is unset.
2. **No platform pricing interface.** Nothing in Layer 0 or Layer 1 calculates a contractual instalment. `lms.calc` is the accrual engine. Forcing the platform engine cannot be implemented by calling it. A platform-engine module is not specified here.
3. **Instalment formula.** Decisions 5 and 13 require the same method. They do not state the formula that produces one contractual instalment from principal, rate, term, frequency, and day-count. Option (a) therefore cannot be computed in the LMS. `Ledger.grant` keeps the caller's lines. This draft asks the originating engine to re-quote and refuses to add a PMT function.
4. **Binding instalment and option (a).** Decision 13 says the accepted instalment stays binding when the dates differ, and says option (a) adjusts the instalment. It does not say whether the stored election is prior consent to the adjusted number. This draft books an adjusted number only when that number is itself the accepted number, and otherwise books neither number.
5. **Quote date and `quoted_disbursement`.** Decision 13 uses the quote date. The ledger uses `quoted_disbursement`. They are not defined as the same day. This draft fails closed when both are present and they differ.
6. **Disbursement before the quote date.** Not covered by decision 13. This draft fails closed.
7. **Remaining term.** Option (a) does not say whether dates move or only the amount changes. Decision 14 names six frequencies and does not define the weekday, the fortnight, or a missing month-end day. The ledger's `next_due_date` raises `due-date-unspecified` rather than clamping. This draft does not define remaining term.
8. **Three different "instalments".** Decision 13's contractual payment, decision 6's threshold instalment (original principal slice plus levied charges that share the due date, including credit life, excluding unbilled interest), and the principal schedule `Servicing.book` stores are not defined as the same figure. `AgreementRecord` and `ElectionSnapshot` have no contractual-instalment field. `propose_residual_write_off` treats exact receipt of the schedule lines as decision 8's exact contractual instalment. This draft does not overload the principal schedule with the payment amount, and it does not add the column. The column needs a lock before it is migrated. The book idempotency fingerprint also omits the contractual instalment.
9. **Cap movement between quote and disbursement.** A later disbursement can fail `Agreement` because the six-month short-term limit is measured from the actual advance, or because the loan has become a subsequent loan at 3 percent. Decision 13 says the accepted instalment is binding. Decision 8 says charges may not exceed NCA limits. The lock does not say whether the loan is refused or re-quoted. This draft leaves the engine rejection in place and does not reclassify the product.
10. **Option (b) "settle early".** The existing settlement interface is `quote_settlement`. The lock does not say that section 125 quote is what option (b) means by settling early. No second formula is added.
11. **Residual write-off.** Decision 8: not automatic, client threshold, R50 when unset, at contractual end. The sub-ledger is not named. Collections posts `write_off_expense` only when `propose_residual_write_off` is called, and also refuses an open in-duplum episode. Decision 8 does not state that episode condition. An older checklist said the write-off is not required when the account is already in default. The current lock does not say that. This draft does not call the write-off at booking and does not treat the episode gate as locked.
12. **Disclosure multiplier.** Decision 17 is periodic rate times periods per year. `periods_per_year` returns 12 or 1 and ignores frequency. Weekly as 52 or as 365/7 is not locked. This draft fails the disclosure check for a frequency those helpers do not already name. `Servicing._annual_equivalent` multiplies `resolved.base_rate`, not `campaign_rate`. Decision 3 requires the price to be shown as base minus discount. The lock does not say which of those two periodic rates is the one decision 17 annualises when a discount is in place. When they differ, intake fails closed instead of storing one and quoting the other.
13. **Affordability figure.** Decision 17 forbids an instalment rounded above the figure already aligned with the client. The lock does not say a missing figure blocks booking, or that the engine should round down instead. This draft enforces the comparison only when the figure is present.
14. **In-duplum trigger at booking.** Decision 19 says an unset election fails closed. `resolve_customer_settings` still allows `None` and records that whether booking must reject it is not settled. `resolve_in_duplum_trigger` does fail closed. `ElectionSnapshot` does not copy the trigger or the residual threshold. This draft calls `resolve_in_duplum_trigger` before `Servicing.book` and does not change Layer 0.
15. **R50 and decision 19.** Decision 19 says unset elections fail closed. Decision 8 names R50 for this one election. `resolve_residual_threshold_cents` already applies 5 000 cents when both levels are null. This draft calls that function and does not reopen the tension.
16. **External-engine principal.** Decision 15 limits Enigma to identity and access. It does not say whether an external engine is a mandate on `agreement.book` or another kind of actor. This draft uses the mandate `Servicing.book` already checks.
17. **Credit-life premium omitted as a blend.** A null premium means no credit life. A positive premium is a separate collection. A blended instalment with no split fails closed. The lock does not say that a missing split should be read as a zero premium. Booking is not blocked merely because credit life is null. Decision 4 requires the premium when collections are automated. It does not say booking fails without it.
18. **Laybye hold and a fixed instalment.** Interest is on principal minus the hold, and the hold can change. The lock does not say whether the binding instalment stays fixed while the base moves (option (b)'s early-settle or residual result) or is recalculated. This draft does not recalculate it.
19. **Further monthly fee codes.** Decision 13 says fixed or variable, outside the amortising schedule. The code list is not locked. A variable fee without an amount fails closed.
20. **Regulation 40(4) alternative.** A method within 0.1 percent of the prescribed method is not a stored election. The day-1 engine uses the prescribed daily method. A quote that uses the alternative cannot be accrued by the existing engine under decision 5. This draft rejects that stamp. Adopting the alternative needs a lock.
21. **NCR comment on `AgreementPin`.** The pin's docstring still copies the NCR number from Enigma. Decision 21 says Enigma does not hold it, the LMS stores it on the organisation, and a blank value does not block booking. This draft follows decision 21.
22. **`dispatch` templates.** The HTTP book route does not load published terms. Intake calls `Servicing.book` with `ProductTerms` from configuration. Leaving the HTTP route as the external entry would drop product overrides. That is an interface gap, not a new election.
23. **Restructure.** Decision 13 allows a new instalment, price, and term during the life of the loan. New agreement versus an amendment of the frozen pin is already open. It is not this intake.
24. **Section 104 notice.** When `repo_rate_fall` is `lower_of_contract_and_cap`, decision 11 requires the notice. Contents and trigger date are not specified. Intake checks that the payload matches the stored choice and does not draft the notice.
25. **Short-term `repo_rate_fall`.** The resolver requires the election for every credit product, including a monthly cap that is not repo-linked. Decision 11 is about a fall in the repo rate. Decision 19 lists the election and does not limit it to an annual cap. Intake calls the resolver as it stands.
26. **Initiation VAT on the book path.** Decision 9 and decision 19 store `exclusive` or `inclusive`. `Servicing._engine_validate` compares `initiation_fee_cents` with `initiation_cap_ex_vat_cents` and does not call `initiation_fee`, which does apply `FeeCapBasis`. The ledger then posts the supplied cents. Intake does not invent a VAT gross-up on that path. A disclosed consumer total that disagrees with `initiation_fee` fails closed.

`IN_DUPLUM_CLIP_POSTS` stays false (decision 7). Intake does not turn the clip on. Three unnamed section 103(5) edges remain unsigned.
