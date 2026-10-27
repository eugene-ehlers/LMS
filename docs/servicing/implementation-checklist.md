# Servicing implementation checklist

Not production code. Nothing in this file is a new business rule. `docs/LOCKED_DECISIONS.md` (last updated 2026-10-27) wins over [primary-flows.md](primary-flows.md) and [implementation-design.md](implementation-design.md).

Build only what is in the locked file. Where a field is required and the value is missing, fail closed. Do not substitute an example number.

## 1. Data structures

Opaque `person_id` and `organisation_id` only. No person or organisation master.

`agreement`

| Field | Rule |
| --- | --- |
| `status` | `pending_disbursement`, `active`, `in_arrears`, `settled`, `disbursement_failed`, `rescinded` |
| `frozen_name`, `frozen_id_number`, `frozen_service_address` | Copied from Enigma at booking. Not updated when Enigma changes. Missing any one of the three fails booking |
| `initiation_fee_capitalised` | Required bool. True: fee is principal, and if capitalised before the default date it is inside the ceiling. False: fee is a section 126 charge |
| `initiation_fee_interest` | `no_interest` (default) or `interest_permitted`. Organisation, with product override |
| `rate_after_repo_fall` | `contract_rate_continues` or `lower_of_contract_and_cap`. No platform default. `not_applicable` when the cap is not a repo formula |
| `vat_on_maxima` | `exclusive` unless the provider has elected `inclusive`. Unset means exclusive |
| `day_count` | `actual_actual` or `30_360`. Provider choice. Omitted fails closed. New-product recommendation `actual_actual` is not a runtime fallback. No separate 360-day-year method |
| `payment_frequency` | `weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual` |
| `prepayment_application` | `reduce_term` or `reduce_instalment`. Omitted fails closed. Keeping the instalment the same is a preference, not a fallback |
| `quote_disbursement_rule` | `adjust_instalment` or `keep_instalment`. Omitted fails closed |
| `base_rate`, `campaign_discount` | Both stored. Net = base minus discount. Net may be 0. A zero fee is valid. Discount remains through leniency, drops on the flag date, and does not return after cure |
| `parent_agreement_id` | Set on the lay-by child. The pair is one loan, not a secured loan |
| `election_snapshot_id` | Frozen at booking. Later policy edits do not change it |

`customer_policy` fields, key unsigned (gap G5): `leniency_days` (calendar days, weekends and public holidays included), `full_payment_threshold_percent`. Either unset fails closed. Do not store 4, 5, or 95 as defaults.

`duplum_episode`

| Field | Rule |
| --- | --- |
| `started_on` | Flag date that opened this episode |
| `ceiling_cents` | Unpaid principal at that date, including a pre-default capitalised initiation fee |
| `accrued_cents` | Charges that accrue during the episode. Charges that caused the default are not included. Post-default accruals count even if a statement shows them as capitalised |
| `closed_on` | Set when the account is brought out of default. The next default inserts a new row and a new ceiling |
| clip | Not a column that suppresses charges. The clip stays off |

`payment`: `recognition_date` is the value date, treated as 00:00 Africa/Johannesburg. `tendered_on` is stored and is not the value date. A reversal uses the original `recognition_date`. `reversed_on` is the processing date only.

`statement_document`: one row per client run, with one section per loan. Each section stores that loan's opening balance, which equals that loan's previous closing balance, and the regulation 35 totals. Prints frozen name, identity number, and service address. Campaign display is base rate and discount.

`tariff_row`: required before a default-administration charge or a collection cost is levied. No row means no levy. Those amounts, when levied, are a further monthly fee (fixed or variable), not a capitalisation into the schedule.

Lay-by child: no second monthly service fee. Interest base for the parent is loan principal minus the hold. `section_124_signed_on` empty means death does not apply the hold. Funeral benefit pays the named beneficiary and does not move the loan or the hold.

## 2. Invariants

1. Value date of an allocation and of its reversal is the recognition date. No time-of-day component.
2. A payment with `recognition_date` equal to the flag date is visible to the default check for that date.
3. Section 126 order is interest, then fees and charges, then principal. A non-capitalised initiation fee is in the fee group. A capitalised one is principal.
4. Default is flagged only on due date + `leniency_days`, and only when the amount received for that due date is below the threshold. The threshold instalment is the original principal slice plus levied charges sharing that due date (service fee, non-capitalised initiation fee, credit life). Unbilled interest is outside that instalment until it is debited.
5. Leniency does not pause interest. Accrual is daily.
6. One service fee, on the lay-by parent. Full monthly fee after the opening month, including the settlement month, subject to the R60 cap. The cap is excluding VAT unless `vat_on_maxima = inclusive`.
7. In-duplum ceiling is not a lifetime ceiling. A payment in the episode does not reset `accrued_cents`. A cure closes the row. No charge is reduced because `accrued_cents` reached `ceiling_cents`.
8. Penalty interest does not exceed the contractual interest rate. The campaign discount is not reapplied after the flag date.
9. Half-up to cents wherever a billed figure is rounded. The same rule everywhere rounding happens.
10. Enigma timeout or an ambiguous Enigma status fails the call. Identity on the agreement is not refreshed from Enigma.
11. Additional fees other than interest, initiation, monthly service fee, and credit life are not written into the amortisation principal.
12. A zero rate or a zero fee does not abort a calculation.

## 3. DRAFT Layer 1 sketch

Draft only. Signatures for the orchestrator. No engine and no ledger implementation. Amounts the engine would return are not computed here.

```text
DRAFT — not an implementation

resolve_elections(organisation_id, product_code, on_date) -> ElectionSnapshot
  # L2 default no_interest. L5 missing on an RR-linked product -> ElectionRequired.
  # VAT unset -> exclusive. day_count missing -> FailClosed.

book(request, snapshot) -> Agreement | FailClosed
  # Freezes name, id number, service address.
  # Calls validate_booking. Does not post charges.

confirm_disbursement(agreement_id, recognition_date, amount_cents) -> Agreement
  # on_disbursement journals for principal and, if not capitalised, a separate initiation fee.
  # Does not post an opening service-fee fraction (gap G4).

recognise_payment(intake) -> Allocated | Unapplied | PrescriptionReview
  # Suspense journal at 00:00 on recognition_date.
  # prepare + allocate. Replay if recognition_date is earlier than a posted allocation.

reverse_payment(payment_id, reversed_on) -> ReplayResult
  # Undo value date = original recognition_date.

morning_default_check(flag_date) -> list[EpisodeOpened]
  # Includes payments recognised on flag_date.
  # Opens an episode. Does not clip.

issue_client_statement(client_key, period_end) -> StatementDocument
  # One document, one section per loan, each with its own opening chain.
  # client_key shape is gap G9. Do not pick one in this draft.
```

## 4. Technical gaps

These are unsigned. Do not close them in code.

| Id | Gap |
| --- | --- |
| G1 | The three section 103(5) edges are not named. The clip stays off. Do not suppress charges when the aggregate meets the ceiling |
| G2 | Locked rule: a capitalised initiation fee is principal. Section 102 lists the agreement types that may include it in principal. Which day-1 products may set the flag is not named. `true` on `short_term` or `unsecured` returns `unresolved_conflict` |
| G3 | After a campaign discount falls away, the rate becomes the base rate. "Penalty interest may not exceed the contractual interest rate" does not say whether contractual means the base rate or the net campaign rate |
| G4 | Opening-month fraction numerator: "inclusive days in the month". The denominator is the actual number of days in that month. The date pair for the numerator is not given, including when disbursement and first due date fall in different calendar months. Do not compute a rand amount |
| G5 | `leniency_days` and the threshold are "per customer". The key (person, or person within one organisation) is not given. The percent's scale is the word "percent"; do not invent a sample threshold |
| G6 | "Amount received for that due date" does not say which receipts qualify (allocated to that instalment's buckets, or any receipt in the window) |
| G7 | Subsequent short-term loans are counted per organisation. Regulation 42 Table A also says "within a calendar year". The locked sentence does not restate the year. Do not drop the year and do not treat the silence as a repeal. Pass prior agreements with their dates and do not apply 3% versus 5% on that point until it is signed |
| G8 | The morning check's clock time is not given. What is given: a flag-date receipt is 00:00 that day and is visible to the check |
| G9 | One statement per client, showing all loans. The client key is not scoped to an organisation. Section 109 still needs each loan's own opening and closing balance inside the document. Do not blend those balances into one figure |
| G10 | Section 126 does not rank fee buckets against each other. Do not code an intra-fee order |
| G11 | Unbilled interest is excluded from the threshold instalment until it is debited. That sentence is not a section 126 allocation rule. Whether a payment takes accrued-but-not-debited interest is still unsigned |
| G12 | Payments may be allocated across the loan and the lay-by. Interest uses principal minus the hold. The cross-allocation order is not stated. Do not add a second waterfall |
| G13 | "Lay-by ≥ settlement balance" does not define the settlement figure's value date or whether the comparison is parent-only |
| G14 | "Disclose the annual equivalent rate" does not choose `monthly × 12` or a compounded effective rate. Store the disclosed figure. Do not derive it |
| G15 | Half-up applies on billing. The scale of unbilled daily amounts is not given. The affordability figure that rounding must not exceed is not given a field |
| G16 | "Small residual" at contractual end has no amount. A restructure creates a new instalment, price, and term. Whether that is a new credit agreement (and therefore a new initiation fee) is not stated |
| G17 | The frequency list has no once-off token. A one-instalment short-term loan has no locked frequency value |
| G18 | Regulation 40 allows the agreement to define the deferred amount as an average or at a time of day. The locked day boundary is 00:00. Whether 00:00 replaces that choice is not stated |
| G19 | The identity freeze is name, identity number, and service address. It does not mention email or telephone, so those are not frozen by this list |
| G20 | The VAT election is described as the provider's. Product-level override is not in the sentence, so it is not built |
| G21 | Lay-by surplus goes to the estate when the hold is a cash deposit, and follows a named beneficiary when it is insurance. Who sets that structure on the child is not given. Death application of the hold requires a section 124 authority signed in life; the authority's document shape is not given |
| G22 | Daily interest during the leniency window is still calculated. The episode starts on the flag date. Whether that leniency-window interest counts toward the in-duplum aggregate is not stated. Do not put it in `accrued_cents` and do not leave the question to a comment in the engine |
| G23 | "The same logic applies to related fee points" does not name the fees other than initiation that may be capitalised |
| G24 | Enigma's real read model is still unknown. Booking needs name, identity number, and service address, and fails closed if the port does not return them |

Form 26 artwork is still a document-layout input, not a rule. The field list remains regulation 35, inside each loan section of the client statement.
