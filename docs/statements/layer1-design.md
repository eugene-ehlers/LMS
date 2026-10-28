# Statements and documents (Layer 1 draft)

Status: **Layer 1, implemented.** The code is `src/lms/statements` and `lms_config.compliance`. It does not change `docs/LOCKED_DECISIONS.md`, and it does not change the Calculation Engine, the ledger, or servicing. PDF bytes are a stub of the stored figures.

The behaviours below cite `docs/LOCKED_DECISIONS.md` by section. A row with no locked section is a gap in [section 9](#9-gaps-that-need-a-locked-decision).

| Behaviour | Locked section |
| --- | --- |
| Value date is the Johannesburg recognition date. Same-day receipts keep recognition order. | §1 |
| On the statement date, accrue, then capitalise amounts due at 00:00, then allocate receipts recognised that day. | §1, §8 |
| Capitalised initiation is inside principal. A fee that was not capitalised stays in its fee bucket. | §2 |
| Base rate and campaign discount are both stored and shown. The discount is not deleted after it falls away. | §3 |
| Lay-by hold is its own balance. It is not subtracted from principal. | §4 |
| Daily accrual uses the snapshot day-count. The statement does not pick a second day-count. | §5 |
| Morning check only on the contractual due date plus leniency days. Unbilled interest is not part of the instalment. | §6 |
| Post-default interest and fees stay in their own buckets. The in-duplum clip is not called. | §7 |
| Allocation is `Ledger.post_payment`, which calls `allocate_payment`. Only that function applies section 126. | §8 |
| Service fee is pro-rata in the opening month and the full fee at later month-ends, including a settlement quote's month. VAT rate is caller-supplied. A missing rate posts nothing. | §9 |
| Interest on a deferred initiation fee is the snapshot election. This layer does not choose. | §10 |
| Repo-fall is the snapshot election. This layer does not issue a section 104 notice. | §11 |
| One statement per client per organisation. Each loan, including a lay-by child, has its own opening and closing bucket balances. The next opening is the previous stored closing. | §12 |
| Instalment shown is the original principal slice plus levied charges that share that due date. Frequency is the snapshot token. | §6, §13, §14 |
| Provider legal name, NCR number, trading name, addresses, telephone, and payment-account details are read from LMS configuration (`ComplianceStore` / `lms.cfg_provider_compliance`), not from Enigma. | Conflict with §15. See C1. Mandate check still calls the servicing Enigma port and fails closed. |
| Consumer name, identity number, and service address are the values frozen on the loan. | §16 |
| Nominal annual rate is `nominal_annual_rate(periodic, periods_per_year)`. Base and effective are both labelled. The single Form 26 annual-rate cell is empty. | §17. Which periodic rate fills that one cell is G16. |
| Default-administration and collection charges are whatever the ledger already posted. This layer does not levy them without a tariff row. | §18 |
| Rates and elections on the statement are the booking snapshot, not a fresh `resolve_customer_settings`. | §19 |
| Section 110 enquiry reads balances and does not call `Ledger.issue_statement`. | §12 for the chain it must not move. The 10- and 20-day deadlines are section 110(2), counted with `add_business_days`. |
| Section 113 quote is `quote_settlement`. Early-termination cents are 0. `valid_until` is `binding_until`. | §1 for the value date. The five business days are section 113, not a locked paragraph. |
| First statement opening, the single section 109 total, the arrears cents, and "interest accrued" as one cell. | Not locked. G1, G2, G4, G5. |

`docs/LOCKED_DECISIONS.md` (last updated 2026-10-28) is the source of truth. Where this note and that file differ, the locked file wins. A point the locked file does not settle is listed in [Gaps that need a locked decision](#9-gaps-that-need-a-locked-decision) and is not given a value here.

This layer calls the Layer 0 functions. It does not re-implement interest, fees, allocation, in-duplum, settlement arithmetic, or business-day counting. The interfaces were read from `origin/cursor/layer0-smoke-4153` at `2ead726` (28 October 2026, 10:30 Africa/Johannesburg) and merged onto this branch. Enigma's port was read from `origin/cursor/enigma-interface-d0c7` at `0cabd41`. Locked decisions on this branch stay the copy from `main`, including capitalise-then-allocate at 00:00.

Dates in this note are Africa/Johannesburg civil dates. `lms_config.calendar.value_date` assigns that date. `value_instant` is 00:00 on that date. The engine does not convert time zones itself.

## 1. What this layer owns

One periodic statement per client per credit-provider organisation, plus two other documents:

| Document | Duty this draft covers | What it does not replace |
| --- | --- | --- |
| Periodic statement | Section 109 chain, regulation 35 / Form 26 fields for a small agreement, principal, interest, fees, arrears inputs, transaction list | A section 110 enquiry, or a section 113 quote |
| Section 110 enquiry | Amount owing and the related figures in section 110(1), on request, without charge | The periodic statement's opening and closing chain |
| Section 113 settlement quote | Section 125 amount, early-termination charge of R0 on a day-1 agreement, binding for five business days after delivery | A periodic statement, and it does not post the settlement |

A written dispute under section 111, and a section 112 adjustment of a debit or credit, are not designed here. They appear only in the gap list, because an immutable statement has no other correction path in the locked file.

The layer stores the figures and an immutable rendering. PDF painting is outlined in [section 3.4](#34-immutable-store-and-pdf-outline). It is not built.

## 2. Statement layout

One document for one `person_id` at one `organisation_id`, for one period. Every loan of that person at that organisation is a section on that document, including a lay-by child account. The document does not include another organisation's loans. Locked decision 12.

Each loan section has its own opening balance and its own closing balance. The next statement's opening for that loan is the stored closing from this statement. That is section 109(1), applied per loan so locked decision 12 still holds. Opening and closing are copied from the stored statement. They are not recomputed from the ledger after the statement has been stored.

### 2.1 Page order

The renderer paints stored figures. It does not call the engine.

1. Logo only, from the logo object key copied onto the statement at issue. See [section 7](#7-branding-and-disclosure).
2. Credit-provider block. Regulation 35(a). Legal name and NCR registration number are compliance fields, not brand fields.
3. Consumer block. Regulation 35(b). Name, identity number, and service address are the values frozen on each loan at booking (locked decision 16).
4. Statement date, and the period covered. Regulation 35(c) and (d).
5. One agreement section per loan, in `loan_id` order. Regulation 35(e), (f), and (g) are inside the section, so each loan keeps the section 109 chain.
6. Inside each section, after the regulation 35 lines: component balances for principal, billed interest, each fee bucket, and the lay-by hold. These are the locked sub-ledgers. They are not merged into principal.
7. The transaction list for that loan. Value date, then recognition sequence (locked decision 1).

A client-level sum of the loan sections is not the section 109 balance. Section 109 is satisfied inside each loan section.

### 2.2 Per-loan section

| Block | What is shown |
| --- | --- |
| Identity | `loan_id` as the agreement reference. Frozen full name, frozen identity number, frozen service address. Payment frequency token from the booking snapshot: `weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual` (locked decision 14). |
| Principal | Outstanding principal bucket. Original principal debt is `cash_advanced_cents`, plus `capitalised_initiation_cents` when the snapshot says the initiation fee was capitalised (locked decision 2). A fee that was not capitalised stays in its fee bucket. |
| Interest | Billed interest bucket, separate from principal. Unbilled accrual memo, labelled as unbilled, and not added to the billed balance (locked decision 6). Base periodic rate, campaign discount, and whether the discount has fallen away (locked decision 3). |
| Fees | One line per ledger bucket: `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`. Ex-VAT and VAT stay as the ledger stored them. The additional monthly fee is not folded into principal (locked decisions 13 and 18). |
| Lay-by | The child account's own opening and closing hold. The hold is not subtracted from principal on the parent (locked decision 4). One service-fee line, on the parent only. |
| Arrears | The inputs listed in [gap G4](#g4-arrears-amount). No arrears total is printed until that gap is locked. |
| In-duplum | Post-default interest and fees stay in their own buckets even where a display total adds them up (locked decision 7). The clip stays off. A statement does not suppress a posted charge. |
| Transactions | See [section 2.3](#23-transaction-list). |

A zero rate and a R0 fee are printed as zero (locked decision 3). The statement does not omit the line.

A short-term or unsecured section uses the regulation 35 field list in [section 5](#5-field-list). A zero-cost or CPA lay-by instrument still has its own opening and closing on the same client document (locked decision 12). Whether that section is Form 26 artwork is [gap G12](#g12-non-nca-instruments-on-the-same-document).

### 2.3 Transaction list

For each loan, for value dates from `period_start` through `period_end` inclusive:

| Column | Source |
| --- | --- |
| Opening line | The previous statement's stored closing for this loan. Regulation 35(g) starts the list from that figure. Section 109(1). |
| Date | `Transaction.value_date`, the Johannesburg recognition date (locked decision 1). |
| Description | Ledger `kind` and `bucket`. Kinds the ledger already posts: `booking`, `laybye_deposit`, `interest_accrual`, `interest_bill`, `charge`, `service_fee`, `payment`, `reversal`, `default_flag`. |
| Debit or credit | Ledger entries. For an owing bucket, a debit increases the amount and a credit decreases it. For `laybye_hold`, a credit increases the hold and a debit decreases it. |
| Amount | Entry cents. Already rounded half-up on billing (locked decision 17). The statement does not round again. |
| Running component balance | Replay of that bucket's entries. |
| Closing line | The component balances stored on this statement. |

Order on one value date is `recognition_sequence` ascending (locked decision 1). Two events at 00:00 stay in the order the system recognised them.

`interest_accrual` is a memo. It has no owing entry. It is listed with the memo rands and is not added to the billed interest running balance. `interest_bill` is the debit. Whether regulation 35(f)(iii) "interest accrued" means the memo or the bill is [gap G5](#g5-interest-accrued-on-form-26).

A `reversal` uses the value date of the transaction it reverses (locked decision 1). If that date falls in a statement that is already stored, the reversal cannot be written into it. See [gap G6](#g6-correction-after-the-statement-is-stored).

### 2.4 Balances the ledger already returns

`Ledger.statement` today returns opening and closing for `principal`, `interest`, and `laybye_hold` only, recomputed from entries. This draft's document also stores opening and closing for every bucket in `lms.ledger.models.BUCKETS`:

`principal`, `interest`, `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`, `laybye_hold`.

The single section 109 total that chains from one statement to the next is [gap G1](#g1-section-109-total). Until it is locked, the chain that is specified is per bucket: each bucket's opening equals that bucket's previous closing. The first statement has no previous closing. Its opening is [gap G2](#g2-first-statement-and-the-period).

## 3. Generation sequence

The user's sequence is the statement-date boundary. The engine's day fold is the implementation of locked decisions 1 and 8. This layer calls that order. It does not add a second capitalisation rule.

Locked decision 1: on a calendar day, accrual and capitalisation of that day's due amounts happen at 00:00 before allocation of payments recognised that day. Locked decision 8: capitalisation and allocation need not fall on the same calendar day. Capitalisation may be month-end. A payment may be on the client's payday. Each is processed on its own recognition date. Only due or unpaid amounts are allocated.

Reading followed here: "capitalise due amounts at 00:00 on the statement date" means the statement date's ordinary day boundary runs, and amounts that are due that day are capitalised then. Issuing a statement does not, by itself, make unbilled interest due. `Servicing.issue_statement` on the Layer 0 branch calls `Ledger.bill_interest` at every `period_end`. That debits the whole unbilled memo. This draft does not copy that call.

The calculation engine bills interest when the day is a month-end or the settlement `as_of` (`lms.calc.ledger._fold_day`). It levies the monthly service fee on those same days. Locked decision 9 fixes the service-fee amount: pro-rata only in the opening month, full monthly fee thereafter, including the settlement month. The engine's `TerminalServiceFee.PRO_RATA` would shorten the settlement month. This layer does not pass it.

When interest becomes due, other than the engine's month-end or settlement bill, is [gap G3](#g3-when-interest-and-fees-become-due).

### 3.1 Before any day is folded

1. Mandate check through the Enigma port. Timeout, an ambiguous status, or a suspended enrolment fails closed (locked decision 15). The servicing `EnigmaStub` is not the port.
2. Load the loans: every `LoanAccount` for that `organisation_id` and `person_id`. Elections come from `ElectionSnapshot` on the account. They are not re-resolved from current organisation settings (locked decision 19).
3. Read the logo key, the provider legal name, and the NCR number as [section 7](#7-branding-and-disclosure) describes. A missing legal name, a missing NCR number, or two different NCR copies on the same statement fails closed ([gap G11](#g11-legal-name-and-ncr-number)).
4. Load the holiday set from `lms.ref_public_holiday` for every year the period and the delivery windows touch. An empty set fails closed. This layer does not call `public_holidays()` as a second calendar.
5. If a stored statement already exists for the same organisation, person, `period_start`, and `period_end`, return it. Do not fold again and do not replace the bytes.
6. If any stored statement for that pair overlaps this period, refuse. The ledger already raises `statement-exists` for an overlap. The period length itself is not locked.
7. If a previous statement exists and a ledger transaction for one of these loans has a value date after that statement's `period_end` and before this `period_start`, refuse. Those entries would sit on no statement. A gap with no transactions is allowed: each bucket opening still equals the previous closing. This is not a statement cycle. Section 108's maximum gap is [gap G7](#g7-section-108-frequency).

`vat_rate` and `interest_cap_present` are required inputs when a service fee or an interest accrual has to be posted. Locked decision 9 does not store a VAT rate. No rate is assumed. A missing interest-cap row fails closed inside `require_reference_for_posting`. Default-administration and collection-cost tariffs fail closed until a tariff row exists (locked decision 18). The statement prints zero for those lines when nothing was levied. It does not invent the charge.

### 3.2 Each civil day through the statement date

Statement date and `period_end` are the same Johannesburg date in this sequence. Regulation 35(c) and (d) allow them to differ. That split is [gap G8](#g8-statement-date-and-period-end).

For each loan, for each date `D` from the first date not yet folded through `period_end`, at `value_instant(D)`, call the existing operations in the engine's day order. Idempotent guards already on the ledger (`already-accrued`, `service-fee-once`) are how a day that was folded earlier is skipped. This layer does not allocate a payment that already has a `payment` transaction.

| Step | What runs | Call |
| --- | --- | --- |
| 1 | Lay-by hold already posted stays as posted. No new hold is calculated here. | Read `laybye_hold` from the ledger. |
| 2 | Morning default check, and only when `D` is a flag date. The flag date is the contractual due date plus `leniency_days` calendar days (locked decision 6). A receipt recognised on that date is visible to the check at 00:00 (locked decisions 1 and 6). | `Servicing.morning_check`, which calls `Ledger.flag_default`, with `due_on` and `check_on=D`. The instalment is the original principal slice plus levied charges that share that due date. Unbilled interest is excluded. `flag_default` posts a `default_flag` row on every call, so this layer does not call it on a day that is not a flag date. It also builds its receipt list from posted `payment` rows only. An unposted flag-date receipt is invisible to it. See [gap G21](#g21-morning-check-and-unposted-receipts). |
| 3 | Accrue that day's interest on the pre-receipt interest base. | `Ledger.accrue_day`. Inside it: `daily_interest_rands`, the snapshot day-count, and the lay-by net base (locked decisions 4 and 5). |
| 4 | Capitalise amounts that are due on `D`. | `Ledger.bill_interest` when `D` is a month-end, or when `D` is a settlement `as_of`. `Ledger.levy_service_fee` when `D` is a month-end or a settlement date, `opening=True` only for the disbursement month, full fee otherwise. `Ledger.levy_charge` only for a charge the engine has already priced and only when a required tariff row exists. |
| 5 | Allocate payments whose value date is `D` and that are not yet posted, after step 4, in recognition sequence. | `lms_config.locked.order_recognised_events`, then `Ledger.post_payment`. Inside it: `lms.calc.allocation.allocate_payment` (locked decision 8). |

`Ledger.post_payment` on the Layer 0 branch allocates at the moment it is called. It does not wait for step 4. A receipt posted at intake before that day's `bill_interest` or `levy_service_fee` is allocated before capitalisation. Locked decision 1 requires the opposite order. This draft does not change `post_payment`. The statement run allocates only receipts that are still unposted, and it does so after step 4. Receipts already posted stay posted. See [gap G9](#g9-receipts-allocated-before-the-days-capitalisation).

Interest for date `D` is accrued before that day's receipts are allocated. The engine calculates that day's interest on the principal from before the receipt. The locked file does not say the receipt also reduces that day's interest. This layer does not add that reduction.

### 3.3 After the last day

For each loan:

1. `Ledger.bucket_balance` for every bucket, `as_of=period_end`, is the closing component balance.
2. The opening component balance is the previous statement's stored closing for that bucket. When there is no previous statement, stop on [gap G2](#g2-first-statement-and-the-period).
3. Opening, plus the signed entries in the period, equals closing, per bucket. A mismatch refuses the statement. Nothing is stored.
4. Regulation 35(f) totals are the sums in [section 5](#5-field-list) for the lines whose membership is mapped. A line marked unsigned is stored as its inputs and is not given a total.
5. Rates to print come from `lms.calc.interest.campaign_terms` on the statement date (base, stored discount, effective rate) and from `nominal_annual_rate` as [section 7.2](#72-annual-equivalent-rate) describes.

Then `Ledger.issue_statement(organisation_id, person_id, period_start, period_end)`. That records the period and refuses an overlap. The wider field list in this draft is stored with that statement. The current `Statement` and `StatementLine` types do not hold it yet. Adding those fields is later implementation, not part of this draft.

### 3.4 Immutable store and PDF outline

The stored statement is the record. The PDF is a painting of that record.

Stored with the statement, and not updated afterwards:

- Organisation, person, period, statement date, statement id.
- Per loan, per bucket: opening cents, closing cents.
- The transaction lines used to prove the chain.
- The regulation 35 inputs, including the lines left unsigned.
- Frozen consumer name, identity number, and service address, copied from the loan.
- Provider legal name and NCR number, copied at issue.
- Logo object key, copied at issue.
- Periodic base rate, campaign discount, discount-fallen-away flag, and the nominal figures from section 7.2.
- SHA-256 of the canonical figure payload.

`lms.client_statement` and `lms.client_statement_balance` already exist and are append-only (update and delete are rejected). They do not yet have the line, rate, name, or hash columns. This draft does not migrate them.

PDF outline, not a renderer:

1. Load the stored statement by id.
2. Paint the copied logo. Paint the copied legal name and NCR number. Do not read `cfg_brand` or Enigma again.
3. Paint each loan section from the stored components and the stored transaction lines, in the order in section 2.
4. Hash the bytes. The first successful painting stores the hash. A later painting that hashes differently is rejected. The figure payload is not regenerated to make the hash match.
5. Until a renderer exists, `pdf` bytes stay empty. The Layer 0 JSON stub (`IssuedStatement.pdf_stub`) is not a PDF and is not delivered as one.

A failed delivery retries against the same stored statement. The retry does not change the issue timestamp or the figures.

## 4. Other documents

### 4.1 Section 110 enquiry

Section 110(1) gives the consumer, on request and without charge, any of:

| Request | What the document shows | Call |
| --- | --- | --- |
| (a) current balance | Component balances per loan from `Ledger.bucket_balance` as at the request value date, after that date's day boundary has run | The sequence in section 3.2 through the request date, then read. Do not call `Ledger.issue_statement`. |
| (b) amounts credited or debited in a requested period | Ledger transactions in that period, same columns as section 2.3 | `transactions_for`, filtered by value date. |
| (c) amounts currently overdue, and when each became due | Unpaid principal slices and unpaid due charges with `due_on` before the request date. Due date is the slice or charge `due_on`. | Read `LoanAccount.slices` and `LoanAccount.charges`. |
| (d) any amount currently payable, and the date it became due | Unpaid slices and unpaid due charges with `due_on` on or before the request date. | Same read. |

The single figure "current balance" uses the same unsigned total as [gap G1](#g1-section-109-total). Overdue versus payable is the split above, which is the ledger's own due dates. It is not a new arrears formula. Unbilled interest is not an overdue amount and is not currently payable (locked decision 6). It is shown only as a memo if the request asks for the balance components.

The enquiry is per loan. Locked decision 12 does not merge credit agreements into one account for this request. A consumer may request several loans in one call. Each loan is answered on its own. The answers are not written into `client_statement` and do not move the section 109 chain.

Delivery, using `lms_config.calendar.add_business_days` and the `ref_public_holiday` set. Section 2(5) of the Act: the request date is excluded, the landing date is included, Saturdays, Sundays, and public holidays are skipped. `add_business_days` already does that. This layer does not count business days itself.

| Rule | Deadline |
| --- | --- |
| Section 110(2)(a): every requested fact is within one year before the request | `add_business_days(request_date, 10, holidays)` |
| Section 110(2)(b): any requested fact is older than one year | `add_business_days(request_date, 20, holidays)` |

The consumer chooses oral or written, and the channel, to the extent the provider is equipped (section 110(3)). A written enquiry is stored: request, loans, figures, delivered-on, channel. An oral enquiry stores the same figures and the delivered-on timestamp. Neither is a periodic statement.

Section 110(4)(a) (a further written statement within three months) and section 110(4)(b) (nothing more than three years after the account was closed) are [gap G10](#g10-section-110-repeat-and-retention). Until they are locked, a request that hits either case fails closed. The layer does not guess whether a different period is a new request, and it does not suppress or produce the document.

Section 110(5), a Tribunal order limiting frivolous requests, is not a platform rule. No limit is hardcoded.

### 4.2 Section 113 settlement quote

One quote per loan. The periodic statement's one-document rule is not a combined settlement figure.

Call `lms.calc.ledger.quote_settlement`. Do not call `lms_config.settlement.early_termination_ceiling_cents`. Do not recompute the total from the component fields.

| Quote field | Source |
| --- | --- |
| `as_of` | The settlement date in the request. The day boundary for that date runs with `settle` set, so the engine bills interest and the full monthly service fee up to that date (locked decision 9). |
| `delivered_on` | The Johannesburg date the quote is delivered. The engine rejects a delivery date before `as_of`. |
| `valid_until` | `SettlementQuote.valid_until`, which is `lms.calc.calendar.binding_until(delivered_on, holidays)`. Five business days after delivery. The delivery date is a valid payment date. The fifth business day after it is the last valid payment date. Weekends and the holiday set are not business days. |
| `principal_cents`, `interest_cents`, `fee_cents`, `components` | The quote. Unpaid principal stays gross of any lay-by hold (locked decision 4). |
| `early_termination_cents` | `0` for a day-1 agreement. |
| `total_cents` | The quote's total. Section 125(2): unpaid principal, plus unpaid interest and other fees and charges up to the settlement date, plus an early-termination charge only on a large agreement. |
| `agreement_size` | The quote. `small`, `intermediate`, or the call fails. |

A large agreement raises `early-termination-unlocked` inside `quote_settlement`. Day-1 agreements stay below that line (the engine rejects a personal loan at or above R250,000 at construction). This layer surfaces that error. It does not price the section 125(2)(c) three-month charge. The constant-balance ceiling in configuration is not a day-1 quote.

The quote is delivered without charge, within five business days of the request: `add_business_days(request_date, 5, holidays)` (section 113(2)(a)). Binding is a different five days: five business days after delivery (section 113(2)(c)), and that date is the quote's `valid_until`. The two dates are not the same count from the same start.

Oral or written follows the consumer's direction (section 113(2)(b)). Both store `delivered_on` and `valid_until`. The stored quote is not edited. A later painting uses the stored quote.

`execute_settlement` is how a payment of the quoted total inside the window settles. It lives on the calculation engine. Posting that result through the ledger is servicing, not this document. This layer does not post it.

Section 113(3) (a credit-facility quote does not bind later draws or charges) is not reached. Day-1 templates are short-term, unsecured, zero-cost, and lay-by. There is no credit facility.

Locked decision 4 says the client can consolidate or settle when the lay-by hold is at least the settlement balance. The engine note already records that this comparison has no second formula. This quote does not add one. The settlement amount remains `SettlementQuote.total_cents`.

Worked shape, not a new example calculation. The engine returns the cents. A day-1 quote looks like this:

| Component | Day-1 rule |
| --- | --- |
| Unpaid principal | Quote `principal_cents` |
| Unpaid interest to `as_of` | Quote `interest_cents` |
| Unpaid fees to `as_of` | Quote `fee_cents`, with `components` naming the buckets |
| Early-termination charge | R0 |
| Settlement amount | Quote `total_cents` |

## 5. Field list

Regulation 35 was read from two public transcriptions on 28 October 2026. They do not match. Acts Online gives "Form 26 **or** must contain" and item (g)(i) "closing balance from the previous statement". A transcription of GN R489 hosted by the PBSA gives "Form 26 **and** must contain" and (g)(i) "opening balance from the previous statement". The NCR's *Guidelines for the form and content of statements of account* also says "opening balance from the previous" in the portion retrieved. This draft does not choose the gazette sentence. Section 109(1) fixes the number: this statement's opening is the previous statement's closing, per loan.

The shared field list is below. "Mapped" means the locked rules and the Layer 0 objects name the source. "Fail closed" means the document is refused until a store exists. "Unsigned" means the cell is not filled.

### 5.1 Regulation 35(a) — credit provider

| Field | Source this draft uses | Lock | State |
| --- | --- | --- | --- |
| (a)(i) name | Provider legal name | Decision 15. Not a brand display name | Fail closed. [Gap G11](#g11-legal-name-and-ncr-number) |
| (a)(ii) trading name, if any | No locked store | Decision 15 | Unsigned. [Gap G13](#g13-regulation-35-provider-contact-fields) |
| (a)(iii) NCR registration number | Pin field `AgreementPin.ncr_registration_number`, if the copies on the loans agree | Decision 15. Not decision 16 | Fail closed. [Gap G11](#g11-legal-name-and-ncr-number) |
| (a)(iv) physical and postal address | No locked store | — | Unsigned. [Gap G13](#g13-regulation-35-provider-contact-fields) |
| (a)(v) telephone | No locked store. `cfg_brand.support_phone` is not read | Branding is the logo only | Unsigned. [Gap G13](#g13-regulation-35-provider-contact-fields) |
| (a)(vi) bank, account number, branch code, payment reference, where relevant | No locked store | — | Unsigned. [Gap G13](#g13-regulation-35-provider-contact-fields) |

### 5.2 Regulation 35(b), (c), (d) — consumer, date, period

| Field | Source | Lock | State |
| --- | --- | --- | --- |
| (b)(i) consumer name | `LoanAccount.frozen_full_name` | Decision 16 | Mapped. If two loans on the statement carry different frozen names, fail closed. [Gap G14](#g14-frozen-identity-differs-across-loans) |
| (b)(ii) account or reference number | `loan_id` on each section | Decision 12, one section per loan | Mapped |
| (b)(iii) consumer address | `LoanAccount.frozen_service_address` | Decision 16 | Mapped, with [gap G15](#g15-address-on-the-statement) |
| Identity number | `LoanAccount.frozen_id_number` | Decision 16. Not a regulation 35(b) line. Printed because the agreement froze it | Mapped |
| (c) statement date | `period_end` in this draft's sequence | Not locked as a separate date | [Gap G8](#g8-statement-date-and-period-end) |
| (d) period covered | `period_start` and `period_end`, supplied by the caller | Decision 12 does not define the period. The ledger refuses an overlap and does not define a cycle | Mapped as caller-supplied bounds, subject to section 3.1 |

### 5.3 Regulation 35(e) — agreement details, per loan

| Field | Source | Lock | State |
| --- | --- | --- | --- |
| (e)(i) principal debt | `cash_advanced_cents`, plus capitalised initiation when the snapshot says so | Decision 2 | Mapped |
| (e)(ii) annual rate of interest | Nominal annual from the periodic rate, section 7.2. Short-term also prints the monthly periodic rate | Decision 17. Regulation 42's monthly disclosure for short-term is the periodic rate | Which periodic rate is multiplied is [gap G16](#g16-which-periodic-rate-is-annualised) |
| (e)(iii) instalment amount | Principal slice amount on the schedule version effective on the statement date, plus levied charges that share that due date. Unbilled interest excluded | Decisions 6 and 13 | Mapped when one schedule version is effective. Two versions effective the same day: fail closed |
| (e)(iv) frequency | Snapshot `payment_frequency` | Decision 14 | Mapped |
| (e)(v) balance outstanding | Component closings | Decisions 2, 4, 6, 7, 12 | The single total is [gap G1](#g1-section-109-total) |
| (e)(vi) in arrears, and the amount | Open episode is a fact. The cents are not | Decisions 6 and 8 describe arrears and do not define the figure | Unsigned. [Gap G4](#g4-arrears-amount) |
| Campaign | Base rate and discount, both printed. Effective rate is base minus discount while the discount applies, and the base after the flag date. The discount stays displayed after it falls away. It does not return on a cure | Decision 3 | Mapped |
| Penalty rate | The base rate after the discount has fallen away. It is not a rate above the contract | Decision 3 | Mapped |

### 5.4 Regulation 35(f) — period summary, per loan

Debits and credits in the period. A line with no posts is zero, except where the row says unsigned.

| Field | Mapped posts | Lock | State |
| --- | --- | --- | --- |
| (f)(i) payments received | `payment` credits, and `reversal` of a payment | Decision 1 | Mapped |
| (f)(ii) fees levied | `initiation`, `service`, `additional_monthly` debits in the period, ex-VAT and VAT as posted | Decisions 2, 9, 13 | `additional_monthly` has no regulation 35 line of its own. Whether it sits inside "fees levied" is [gap G17](#g17-additional-monthly-fee-and-legal-fees-on-form-26) |
| (f)(iii) interest accrued | `interest_accrual` memo rands, and `interest_bill` cents, stored separately | Decisions 5 and 6 | Unsigned which of the two the cell uses. [Gap G5](#g5-interest-accrued-on-form-26) |
| (f)(iv) insurance costs levied | `credit_insurance` | Decision 6 includes credit life in the instalment | Mapped |
| (f)(v) collection costs levied | `collection_costs` | Decision 8. Decision 18: no tariff, no post | Mapped. Zero when none levied |
| (f)(vi) default administration costs levied | `default_administration` | Decisions 8 and 18 | Mapped. Zero when none levied |
| (f)(vii) legal fees incurred | No ledger bucket | — | Unsigned. Printed only after a bucket exists. Not posted into `collection_costs`. [Gap G17](#g17-additional-monthly-fee-and-legal-fees-on-form-26) |

Fee order when several buckets are due is an allocation rule (locked decision 8: collection costs, default administration, credit insurance, service fee, initiation fee, earliest due date first within a bucket). The statement lists the buckets. It does not re-allocate.

### 5.5 Regulation 35(g) — transaction detail, per loan

| Field | Source | Lock | State |
| --- | --- | --- | --- |
| (g)(i) previous closing, carried as this opening | Stored closing of the previous statement, per bucket and, once locked, per section 109 total | Decision 12 and section 109(1) | Per bucket: mapped. Single total: [gap G1](#g1-section-109-total). Wording of the regulation: transcription conflict above |
| (g)(ii) date | `value_date` | Decision 1 | Mapped |
| (g)(iii) description | `kind` and `bucket` | — | Mapped as those tokens. No separate wording list is locked |
| (g)(iv) amount and debit or credit | Ledger entries | Decision 17, already rounded | Mapped |
| (g)(v) running total | Per-bucket replay | The single running total follows gap G1 | Per bucket: mapped |
| (g)(vi) closing balance | Stored closing | Decision 12 | Per bucket: mapped. Single total: gap G1 |

### 5.6 Component lines the regulation does not name

These are required by the locked decisions and are stored even if a later Form 26 painting omits them. They are not dropped from the stored figures.

| Line | Rule |
| --- | --- |
| Principal bucket closing | Decisions 2 and 7. Capitalised initiation that was capitalised before default sits in principal. Post-default accruals do not |
| Billed interest closing | Decision 6, after `interest_bill` |
| Unbilled interest memo | Decision 6. Excluded from the instalment test and from arrears until debited |
| Each fee bucket | Decisions 8, 9, 13, 18 |
| Lay-by hold opening and closing | Decision 4. Not netted off principal |
| In-duplum episode ceiling and accrued counter | Decision 7. Display only. The clip is off, so the counter does not change the amount |
| VAT split on each fee | Decision 9. The snapshot's `vat_on_rand_maxima` is `exclusive` or `inclusive`. The statement prints the split the ledger posted |

## 6. Sequence of calls

Money functions are only those below. Configuration reads that are not money (logo, holidays, pin) are named as reads.

### 6.1 Periodic statement

```
Documents layer
  |  Enigma port: mandate for this organisation and person
  |  fail closed on timeout, ambiguous status, suspended enrolment     §15
  |
  |  Ledger: accounts for (organisation_id, person_id)
  |  elections = LoanAccount.snapshot                                   §19
  |  frozen name, id number, service address                            §16
  |
  |  Configuration read: cfg_brand.logo_object_key                      logo only
  |  Configuration read: NCR number on the agreement pin                gap G11
  |  Provider legal name                                                 gap G11, fail closed
  |  Configuration read: lms.ref_public_holiday
  |
  |  for each loan, for each date D through period_end at 00:00:
  |      if D is a flag date (due date + leniency_days):
  |          Servicing.morning_check
  |              -> Ledger.flag_default
  |                  -> is_in_default_at_morning_check                  §1 §6
  |              posted receipts only; unposted receipts are gap G21
  |      Ledger.accrue_day
  |          -> require_reference_for_posting                           cap row or fail
  |          -> lms.calc.interest.daily_interest_rands                  §4 §5
  |      if D is month-end or a settlement as_of:
  |          Ledger.bill_interest                                       due interest only
  |          Ledger.levy_service_fee
  |              -> opening_service_fraction (opening month only)       §9
  |              -> service_fee_cents                                   §9
  |      Ledger.levy_charge only with a priced charge and a tariff row  §18
  |      order_recognised_events of unposted receipts on D              §1
  |      Ledger.post_payment
  |          -> lms.calc.allocation.allocate_payment                    §8
  |
  |  Ledger.bucket_balance per bucket, as_of period_end
  |  previous statement closing -> this opening                         §12, s 109
  |  lms.calc.interest.campaign_terms                                   §3
  |  lms.calc.interest.nominal_annual_rate(
  |      periodic, periods_per_year(product))                           §17, gap G16
  |
  |  Ledger.issue_statement(organisation, person, period_start, period_end)
  |  store figures, copied names, logo key, payload hash
  |  PDF paint later, from the store only
```

`nominal_annual_rate` in `lms_config.locked` is the same formula. The statement calls the engine function so disclosure and accrual share one implementation.

`periods_per_year` is 12 for a micro (short-term) product and 1 for a personal (unsecured) product. A personal periodic rate is already an annual rate, so the nominal figure equals that periodic rate. A zero periodic rate yields a zero nominal rate.

### 6.2 Section 110

```
Documents layer
  |  Enigma port: mandate                                               §15
  |  day boundary through the request date, same calls as §6.1
  |  do not call Ledger.issue_statement
  |  Ledger.bucket_balance as at the request date                       s 110(1)(a)
  |  ledger transactions in the requested value-date range              s 110(1)(b)
  |  unpaid slices and charges, by due_on                               s 110(1)(c)(d)
  |  add_business_days(request_date, 10 or 20, ref_public_holiday)      s 110(2)
  |  store the enquiry. it is not a client_statement
```

### 6.3 Section 113

```
Documents layer
  |  Enigma port: mandate                                               §15
  |  assemble Agreement, events, and Policy from the ledger snapshot
  |      elections from ElectionSnapshot, not from live settings        §19
  |      holidays from ref_public_holiday
  |  lms.calc.ledger.quote_settlement(
  |      agreement, events,
  |      as_of=settlement date,
  |      delivered_on=delivery date,
  |      policy, repos, vat_rates, holidays)
  |      -> SettlementQuote
  |      -> binding_until(delivered_on, holidays)                       s 113(2)(c)
  |      -> early_termination_cents = 0, or early-termination-unlocked
  |  add_business_days(request_date, 5, holidays)                       s 113(2)(a)
  |  store the quote
  |  do not call early_termination_ceiling_cents
  |  do not call execute_settlement from this layer
```

The `Agreement` handed to `quote_settlement` is built from facts the ledger and the snapshot already store: product, ids, cash advanced, advance date, contractual end, rates, schedule, campaign discount, initiation capitalisation, day-count, and the frozen elections. The documents layer does not recalculate those facts.

### 6.4 Calls this layer does not make

| Not called | Why |
| --- | --- |
| `lms.calc.ledger.run` as a second book | The ledger is the book. `run` would re-implement the posted history |
| `early_termination_ceiling_cents` | Day-1 early-termination charge is R0. The ceiling formula is not locked |
| `TerminalServiceFee.PRO_RATA` | Locked decision 9 requires the full service fee in the settlement month |
| `Ledger.clip_in_duplum` | Locked decision 7: the clip stays off |
| `resolve_customer_settings` at statement time | Elections were copied at booking |
| `cfg_brand.display_name`, `support_phone`, `support_email`, `statement_footer` | Branding is the logo only |
| `EnigmaStub` | Not the identity port |
| `read_live_identity` for the name or address on the statement | Decision 16 freezes those on the loan |
| A new NCR or legal-name column | Decision 15. Gap G11 has to be locked before any new store |

## 7. Branding and disclosure

### 7.1 Logo only

`lms.cfg_brand` stores `display_name`, `support_phone`, `support_email`, `logo_object_key`, and `statement_footer`. Branding on these documents is `logo_object_key` only. The other four columns are not painted and are not used as the credit provider's legal name, telephone, or address.

The logo key is copied onto the stored statement. A later change to `cfg_brand` does not change a statement already stored.

If the organisation has no `cfg_brand` row, the statement has no logo and still proceeds, provided legal name and NCR number are present. If it has more than one row, this layer does not pick one. See [gap G18](#g18-which-logo).

The calculation engine does not read `cfg_brand`. This layer does not put the logo on the accrual path.

### 7.2 Annual-equivalent rate

Locked decision 17: the annual-equivalent rate for disclosure is the periodic rate times the number of periods per year. Simple nominal, not an effective compounded rate. Disclose both the periodic rate and the nominal annual rate.

The engine function is `lms.calc.interest.nominal_annual_rate(periodic_rate, periods_per_year)`.

Locked decision 3 requires the statement to show the base rate and the campaign discount as two figures. The effective periodic rate is base minus discount while the discount applies, and the base rate on and after the default flag date. Both the base and the discount are printed in every case, including after the discount has fallen away, and including when either figure is zero.

Which of those periodic rates is the one decision 17 multiplies is [gap G16](#g16-which-periodic-rate-is-annualised). Until it is locked, the statement stores:

- periodic base rate, from the snapshot
- campaign discount, from the snapshot
- effective periodic rate, from `campaign_terms`
- nominal annual of the base, and nominal annual of the effective rate, each labelled with the periodic rate that was multiplied

It does not print one unlabelled "annual rate" in the regulation 35(e)(ii) cell. `Servicing._annual_equivalent` currently multiplies `resolved.base_rate` once, at booking. That is a Layer 0 choice, not decision 17. This layer does not copy it into the Form 26 cell.

## 8. Conflicts found

These are disagreements between the locked file, the Act or regulations, and designs or code that already exist. This draft does not resolve them.

| # | What conflicts | What this draft does |
| --- | --- | --- |
| C1 | Locked decision 15: the LMS stores only opaque organisation ids and does not re-implement organisation identity. The statements task says legal name, NCR number, trading name, addresses, telephone, and payment-account details are read from LMS configuration, not from Enigma. `docs/lms-owned-configuration.md` says the LMS does not own legal name or the NCR number. The Enigma port returns `legal_name` and says Enigma does not hold the NCR number. | The statements layer reads `lms_config.compliance.ComplianceStore` (table `lms.cfg_provider_compliance`). It does not call Enigma for those fields. It does not change decision 15. A missing or blank required field fails closed. Consumer identity stays the frozen loan fields (decision 16). |
| C2 | `cfg_brand` carries a display name, support contacts, and a footer. Regulation 35(a) requires a trading name, addresses, a telephone, and payment-account details. | Those regulation 35 fields are copied from `ProviderCompliance`, not from `cfg_brand`. The logo is not painted in this implementation (G18). |
| C3 | Two transcriptions of regulation 35 disagree on "Form 26 or" versus "Form 26 and", and on whether item (g)(i) is the previous closing balance or the previous opening balance. | Use section 109(1): this opening equals the previous closing, per loan. Do not pick the gazette sentence. |
| C4 | An earlier servicing note printed the consumer address "as at the statement date". Locked decision 16 freezes the service address at booking. | Print the frozen service address. Gap G15 records the regulation's word "address". |
| C5 | An earlier servicing note put a lay-by pair in one statement section. The ledger keeps a child account with its own balances. Locked decision 4 says the pair is one loan and not security. Locked decision 12 says each loan keeps its own opening and closing balance. | One client document. Parent and child each keep the balances the ledger stores. They are not added together and the hold is not netted off principal. |
| C6 | `Servicing.issue_statement` bills all unbilled interest at `period_end`. Locked decisions 1 and 8 capitalise amounts that are due, and they allow capitalisation on a day that is not the payment day. Locked decision 6 leaves interest unbilled until it is debited. | Do not call `bill_interest` merely because the day is the statement date. |
| C7 | `Ledger.post_payment` allocates when it is called. Locked decision 1 allocates a day's receipts after that day's due amounts are capitalised. | The statement sequence allocates only receipts that are still unposted, and only after capitalisation. Already-posted receipts are gap G9. |
| C8 | `TerminalServiceFee.PRO_RATA` remains on the engine. Locked decision 9 charges the full monthly service fee in the settlement month. | This layer does not pass `PRO_RATA`. |
| C9 | The engine previews a flag-date receipt before allocation, then can cure later inside the day fold. `Ledger.flag_default` sees posted payments only and writes a `default_flag` row on every call. Decision 6 flags only on the flag date. | The statement sequence calls `morning_check` only on the flag date. Unposted receipts and a later cure are gap G21. This layer does not re-implement the predicate. |

## 9. Gaps that need a locked decision

None of these is given a locked default. Where the code stores a labelled figure or returns an enquiry anyway, the item says so. It does not invent the missing rule.

### G1. Section 109 total

Decisions 2, 4, 6, 7, and 12 constrain the components. They do not state the single opening and closing figure. In particular they do not say whether that figure adds every owing bucket, and they do not say that unbilled interest and the lay-by hold stay outside it. Per-bucket opening and closing are specified. The single total is not filled.

### G2. First statement and the period

There is no previous closing for the first statement. The locked file does not say whether the opening is zero before the advance, or the position after disbursement. The caller supplies `period_start` and `period_end`. Overlap is refused. A gap that contains transactions is refused. No monthly cycle is assumed.

### G3. When interest and fees become due

Decision 8 says capitalisation may be month-end and need not be the payday. The engine bills interest and levies the service fee on month-end and on settlement. The locked file does not say interest becomes due on the contractual payment date, or on the statement date. This sequence follows the engine's month-end and settlement bills only.

### G4. Arrears amount

Regulation 35(e)(vi) asks whether the account is in arrears and for the amount. Decisions 6 and 8 say a shortfall against the contractual instalment becomes arrears. They do not define the cents. The statement stores the open episode, if any, and the unpaid slices and charges with their due dates. It does not print an arrears total.

### G5. Interest accrued on Form 26

Regulation 35(f)(iii) says "interest accrued". The ledger stores a daily memo (`interest_accrual`) and a later debit (`interest_bill`). Decision 6 excludes unbilled interest until it is debited. Which figure the cell uses is not locked. Both are stored. The cell is not filled.

### G6. Correction after the statement is stored

A stored statement is immutable, and section 109(1) requires the next opening to equal this closing. A reversal uses the original value date (decision 1). If that date is already inside a stored statement, the reversal cannot be inserted and a recomputed opening would break the chain. Section 112 is the Act's adjustment mechanism. It is not in the locked file. No adjustment line is specified.

### G7. Section 108 frequency

Section 108 limits how far apart periodic statements may be, by agreement type, with a narrower agreed interval in some cases. The locked file does not set that interval and does not record the consumer's election. This layer does not invent a monthly run and does not reject a longer gap that contains no skipped transactions.

### G8. Statement date and period end

This sequence uses one Johannesburg date for both, because capitalisation and accrual-to-period-end are described as one boundary. Regulation 35(c) and (d) are separate fields. A statement date other than `period_end` is not specified.

### G9. Receipts allocated before the day's capitalisation

Intake that calls `post_payment` before that value date's `bill_interest` and `levy_service_fee` has already allocated. This layer does not reverse those posts and does not allocate them again. How a same-day receipt waits for capitalisation is not locked.

### G10. Section 110 repeat and retention

Section 110(4)(a) excuses a further written statement within three months. Section 110(4)(b) excuses information more than three years after closure. The locked file does not say what "such a statement" covers, or which event closes the account for the three-year count. The enquiry still returns the figures. It does not refuse, and it does not write a periodic statement.

### G11. Legal name and NCR number

Conflict C1. The statements task names LMS configuration as the source. `ComplianceStore.require` fails closed when the row is missing or a required field is blank. Decision 15 is unchanged, so this store is not a locked rule. Whether a zero-cost or lay-by-only statement may omit the NCR number is still not in the locked file. The code requires the number for every statement.

### G12. Non-NCA instruments on the same document

Decision 12 puts every loan of the client at that organisation on the one statement. Form 26 is the small-agreement form. The locked file does not say whether a zero-cost or CPA lay-by section is painted as Form 26. The section keeps its own balances either way.

### G13. Regulation 35 provider contact fields

Trading name, physical address, postal address, telephone, and the payment-account details are read from the same LMS compliance row as the legal name (C1). They are not in the locked election list (decision 19). Trading name may be blank because regulation 35(a)(ii) says "if any". The other fields fail closed when blank. Decision 15 does not name this row.

### G14. Frozen identity differs across loans

Decision 16 freezes name, identity number, and service address at each booking. A later booking can freeze a different name. Regulation 35(b)(i) is one consumer name on the document. No rule picks among the frozen names. Each loan section keeps the name frozen on that loan. The code does not refuse when those names differ, and it does not pick one name for the document. This remains open.

### G15. Address on the statement

The field printed is the frozen service address. Regulation 35(b)(iii) says "the consumer's address" and does not say "service address frozen at booking". A current postal address would be a second fact. It is not read.

### G16. Which periodic rate is annualised

Decision 17 multiplies "the periodic rate". Decision 3 requires base and discount both to be displayed, and the rate in force changes when the discount falls away. The two nominal products (base times periods per year, and effective times periods per year) are stored and labelled. The single regulation 35(e)(ii) cell is not filled.

### G17. Additional monthly fee and legal fees on Form 26

`additional_monthly` is a locked fee bucket with no regulation 35 line of its own. Legal fees are a regulation 35(f)(vii) line with no ledger bucket. Neither is merged into another line.

### G18. Which logo

`cfg_brand` is keyed by `(organisation_id, brand_code)`. The booking record on the Layer 0 branch does not store a brand code. Zero rows: no logo. More than one row: fail closed, no row is chosen.

### G19. Intermediate and large form

Section 109(2) puts a small agreement on the prescribed form. Section 109(3) lets an intermediate or large agreement use the prescribed form or a provider form that meets the prescribed requirements. Day-1 personal loans can be intermediate and still sit under R250,000. No locked decision chooses the form. The component store is the same. The PDF artwork for an intermediate section is not specified. A large agreement is not quoted and is not given an early-termination charge.

### G20. Section 104 notice

Decision 11's `lower_of_contract_and_cap` choice issues a section 104 notice. The rate printed on the statement is the rate the ledger accrued. This layer does not produce the notice.

### G21. Morning check and unposted receipts

Decision 6 flags default only on the flag date. Decision 1 says a payment received that day is visible to the morning check, and decision 1 also allocates that payment after capitalisation. `Ledger.flag_default` can see a receipt only after a `payment` transaction exists, and it writes a `default_flag` transaction every time it is called, including when it neither opens nor closes an episode. The engine previews the day's receipts and can cure inside the day fold. There is no ledger method that previews an unposted receipt or that cures without posting. This sequence calls the morning check only on the flag date, and only through `flag_default`. It does not re-implement `is_in_default_at_morning_check` in order to see receipts that are still unposted. A cure on a later payment day is the same gap.

## 10. Out of scope

- Production code, migrations, PDF rendering, and delivery transport.
- Section 111 disputes and section 112 adjustments, except as gap G6.
- Posting `execute_settlement` through the ledger.
- The section 125(2)(c) early-termination formula. Day-1 charge is R0.
- Credit-facility quotes under section 113(3).
- A combined settlement across a lay-by pair.
- Changing any Layer 0 function.
