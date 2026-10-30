# Statement PDF and document rendering (Layer 2 draft)

Status: **Layer 2 draft.** Design only. No renderer, no migration, and no change to `docs/LOCKED_DECISIONS.md`.

This note describes how a PDF is painted from figures the Statements layer has already stored. It does not issue a statement, fold a day, or recalculate a balance. Where this note and `docs/LOCKED_DECISIONS.md` differ, the locked file wins. A point the locked file does not settle is listed in [Gaps that need a locked decision](#9-gaps-that-need-a-locked-decision) and is not given a value here.

Dates in this note are Africa/Johannesburg civil dates. The Statements layer already assigned them with `lms_config.calendar.value_date`. This layer does not convert time zones.

## Interfaces this draft calls

Read on 28 October 2026 from `origin/cursor/layer1-gap-closures-ccde` at `a99b1b5` (13:09 Africa/Johannesburg). That commit carries the statements implementation from `144e331` and the current locked file, which matches `main` at `197600d` (11:18 Africa/Johannesburg).

| Piece | Where it lives | What this layer uses |
| --- | --- | --- |
| Statements | `lms.statements.Documents` | `issue_statement` returns the stored statement again on the same period key and does not fold again. `settlement_quote` returns the stored quote again on the same `(agreement_id, as_of, delivered_on)` and does not call `quote_settlement` again. |
| Statement figures | `StoredStatement`, `LoanSection`, `TransactionView` | The only figures a periodic PDF may paint. |
| Enquiry | `AmountOwing` from `Documents.enquire` | Painted as returned. `enquire` itself is not a paint call: it folds the ledger. |
| Quote | `StoredQuote` | The only figures a section 113 PDF may paint. |
| Provider configuration | `lms_config.compliance.ComplianceStore.require` | Already called inside `issue_statement`, which copies the row onto `StoredStatement`. This layer does not call it again. |
| Brand table | `lms.cfg_brand` | No Python reader. The stored statement has no logo key. See [P1](#p1-which-logo). |

`Documents` is constructed with a `Servicing` and a `ComplianceStore`. This layer does not construct a second one and does not call the ledger, the calculation engine, or `Servicing.issue_statement`.

## 1. What this layer owns

Three paintings. Each one is a view of a Statements-layer result. None of them is a new calculation.

| Document | Painted from | Duty |
| --- | --- | --- |
| Periodic statement | One `StoredStatement` | One client, one credit-provider organisation, every loan of that pair as its own section. Regulation 35 / Form 26 fields for a small agreement, where the stored section actually holds the figure. |
| Section 110 enquiry | One `AmountOwing` | Amount owing for one loan. Not a periodic statement, and not a section 109 opening. |
| Section 113 settlement quote | One `StoredQuote` | Settlement amount, early-termination charge of R0, binding date and delivery deadline already stored on the quote. |

A written dispute under section 111, and a section 112 adjustment, are not designed here. The Statements layer stores no adjustment line. This layer does not add one.

Credit-life statements and accounts stay with the insurer (locked decision 4). The `credit_insurance` cents on a loan section are the premium the loan statement already stores. They are not an insurer statement.

## 2. Rendering rule

The PDF is a painting of the already-stored statement figures. It is not rebuilt from the ledger at render time.

1. The painter receives the object the Statements layer already returned. It reads fields on that object. It does not call `Ledger.bucket_balance`, `Ledger.statement`, `quote_settlement`, `nominal_annual_rate`, `campaign_rate`, `add_business_days`, or `binding_until`.
2. Each loan's opening cents are `LoanSection.opening`. When `opening_source` is `previous-closing`, that opening is the previous stored closing for that loan (locked decision 12 and section 109). The painter does not load the previous statement to recompute it. The Statements layer already refused the issue when the two differed (`opening-chain`).
3. When `opening_source` is `no-previous-statement`, the painter prints the stored opening and that source token. It does not caption the figure as a previous closing. The first opening is [P2](#p2-first-statement-opening).
4. A stored zero is printed as zero, including a zero rate and a R0 fee (locked decision 3). A stored `None` is left blank. Zero and blank are not interchangeable.
5. Money on the page is the stored integer cents, shown as rands by dividing by 100, with two fraction digits. Locked decision 17 already rounded half-up to cents at billing. This layer does not round again. The thousands-separator glyph is not locked and is not chosen here.
6. A rate on the page is the stored `Decimal`, printed as stored. This layer does not choose a display scale and does not multiply a rate. The annual-equivalent figures were already produced inside the Statements layer as periodic rate times periods per year (locked decision 17).
7. `StoredStatement.pdf_stub` is the bytes `PDF-STUB` plus a JSON payload. `pdf_sha256` is the hash of those bytes. Neither is a PDF. This layer does not deliver the stub and does not replace the hash. See [P3](#p3-the-stored-hash-is-the-stub).

A replay used only to draw a running balance is defined in [section 3.4](#34-transaction-list). It uses the stored opening and the stored lines. It does not read the ledger. If the replay does not meet the stored closing, the PDF is not produced and no figure is altered.

## 3. Periodic statement layout

One PDF for one `StoredStatement`: one `person_id` at one `organisation_id`, for one period (locked decision 12). Loan sections are painted in the tuple order `issue_statement` stored, which is `loan_id` order. The painter does not sort them again and does not drop a loan.

The page is not a redraw of the Form 26 graphic. The gazette artwork is [P4](#p4-form-26-artwork-and-the-regulation-35-transcription). The reading order below is the field order. It is the same order for every loan section. Whether an intermediate section, or a zero-cost or lay-by section, may use that order as its prescribed form is [P5](#p5-intermediate-agreement-artwork) and [P6](#p6-non-nca-sections-on-the-same-document). Until those are locked, the page is not titled as the prescribed Form 26, and no second artwork is invented.

### 3.1 Page order

1. Logo position. It stays empty. Branding is the logo only, and the stored statement has no logo key. `display_name`, `support_phone`, `support_email`, `statement_footer`, and any brand colour are not painted. See [P1](#p1-which-logo).
2. Credit-provider block, from the fields copied onto the statement at issue. Regulation 35(a). Legal name and NCR number are these compliance fields, not brand fields.
3. Document control: `statement_id`, `statement_date`, `period_start`, `period_end`. The opaque `organisation_id` and `person_id` are printed as document keys. They are not the consumer's identity number (locked decision 15).
4. One agreement section per loan, in stored order. Regulation 35(b), (e), (f), and (g) sit inside the section, so each loan keeps its own section 109 chain. There is no document-level consumer name. See [P7](#p7-frozen-identity-differs-across-loans).
5. Inside each section, after the regulation 35 lines: one row per stored bucket for opening and closing. The buckets are `principal`, `interest`, `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`, and `laybye_hold`. They are not added together. The lay-by hold is not subtracted from principal (locked decision 4).
6. The transaction list for that loan.

A client-level sum of the sections is not printed. Section 109 is satisfied inside each loan section. The single balance cell stays blank ([P8](#p8-single-balance-total)).

### 3.2 Credit-provider block

Painted only from `StoredStatement`. `ComplianceStore` is not read at paint time, so a later `put` cannot change a statement that was already stored.

| Line | Stored field | When the value is blank |
| --- | --- | --- |
| Legal name | `legal_name` | A stored statement cannot have this blank. `ComplianceStore.require` refuses it before issue. |
| Trading name | `trading_name` | The line is omitted. Regulation 35(a)(ii) says "if any", and the compliance row allows a blank trading name. |
| NCR registration number | `ncr_registration_number` | A stored statement cannot have this blank. Decision 21 blocks an NCA communication when the number is blank. This layer does not relax that for a zero-cost or lay-by section that shares the document. |
| Physical address | `physical_address` | Cannot be blank on a stored statement. |
| Postal address | `postal_address` | Cannot be blank on a stored statement. |
| Telephone | `telephone` | Cannot be blank on a stored statement. This is the compliance telephone, not `cfg_brand.support_phone`. |
| Bank, account number, branch code, payment reference | `bank_name`, `bank_account_number`, `branch_code`, `payment_reference` | Cannot be blank on a stored statement. |

### 3.3 Per-loan section

| Block | What is painted |
| --- | --- |
| Identity | `loan_id` as the agreement reference. `parent_loan_id` when it is present. `instrument_kind`. `frozen_full_name`, `frozen_id_number`, `frozen_service_address` (locked decision 16). `payment_frequency` as the stored token: `weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual` (locked decision 14). |
| Principal debt | `principal_debt_cents`. The Statements layer already set this to cash advanced plus capitalised initiation when the booking snapshot capitalised the fee (locked decision 2). This layer does not add those parts again. |
| Rates | `base_rate` and `discount_rate`, both, including after the discount has fallen away and including when either is zero (locked decision 3). `discount_fallen_away` as stored. `periodic_rate_in_force`, `nominal_annual_on_base`, and `nominal_annual_on_effective` when they are stored, each labelled with which periodic rate was multiplied. The single regulation 35(e)(ii) cell is `annual_rate_cell`, which is always `None`, so it stays blank ([P9](#p9-which-periodic-rate-fills-the-form-26-cell)). |
| Instalment | `instalment_cents` and `instalment_due_on`. A `None` is blank. The Statements layer already built the cents as the principal slice plus levied charges that share that due date, excluding `additional_monthly` and excluding unbilled interest (locked decision 6). This layer does not rebuild it. |
| Balances | Per-bucket `opening` and `closing`. No single outstanding total ([P8](#p8-single-balance-total)). |
| Arrears | `open_default_episode` as the stored fact, and each `overdue` row `(bucket, due date, cents)`. `arrears_cents` is `None`, so the amount cell stays blank ([P10](#p10-arrears-amount)). |
| Fees in the period | The named stored cents: `insurance_levied_cents`, `collection_levied_cents`, `default_administration_levied_cents`. The single "fees levied" cell is not filled from `fees_levied_cents` ([P11](#p11-fees-levied-and-legal-fees)). `legal_fees_cents` is `None`, so that cell stays blank. |
| Interest in the period | `interest_billed_cents` labelled as interest billed, and `interest_memo_rands` labelled as the unbilled memo. They are not added. The single "interest accrued" cell stays blank ([P12](#p12-interest-accrued-cell)). |
| Lay-by | The child section's own opening and closing `laybye_hold`. The parent's principal is not reduced by the hold (locked decision 4). A zero service bucket on the child is printed as zero. |

Post-default interest and fees stay in the buckets where they were stored (locked decision 7). The in-duplum clip is not painted as a reduction. The episode ceiling is not on `LoanSection`. See [P13](#p13-figures-the-stored-section-does-not-carry).

### 3.4 Transaction list

For each loan, the list is `LoanSection.transactions` in the order stored. That order is value date, then recognition sequence (locked decision 1). The painter does not sort again.

| Row | Source |
| --- | --- |
| Opening line | `LoanSection.opening` for every bucket. Caption "previous closing" only when `opening_source` is `previous-closing`. |
| Date | `TransactionView.value_date`. |
| Description | `TransactionView.description`, which the Statements layer set from `kind` and `bucket`. No separate wording list is locked, so the tokens are printed as stored. |
| Debit or credit | `debit_cents` and `credit_cents`. |
| Memo | `memo_rands` on an `interest_accrual` line. It is not added to the billed interest balance. |
| Running balance | Replay below. |
| Closing line | `LoanSection.closing`. |

The replay starts from the stored opening of that bucket and walks the stored lines for that bucket:

- An owing bucket moves by `debit_cents - credit_cents`. That is the sign `Ledger.bucket_balance` already uses. This layer does not call it.
- `laybye_hold` moves by `credit_cents - debit_cents`. A credit increases the hold. The hold is still not netted off principal.
- A line with a memo and no debit or credit does not move the balance.

If the replay of any bucket does not equal that bucket's stored closing, the PDF is refused. Nothing is written back to the statement, and no section 112 line is added.

### 3.5 Cells that stay blank

These stored sentinels are printed as an empty cell, not as zero and not as a substitute formula.

| Cell | Stored sentinel | Why it stays blank |
| --- | --- | --- |
| Regulation 35(e)(ii) single annual rate | `annual_rate_cell is None` | Decision 17 names "the periodic rate". Decision 3 requires base and discount both to be shown. Which periodic rate is multiplied into that one cell is [P9](#p9-which-periodic-rate-fills-the-form-26-cell). Both nominals are printed beside the blank cell, labelled. |
| Regulation 35(e)(v) one balance outstanding | No field | [P8](#p8-single-balance-total). Per-bucket closings are printed. |
| Regulation 35(e)(vi) arrears amount | `arrears_cents is None` | [P10](#p10-arrears-amount). The episode flag and the overdue rows are printed. |
| Regulation 35(f)(ii) fees levied | `fees_levied_cents` exists and is not used as this cell | The stored sum adds initiation, service, and `additional_monthly`. Membership of the cell is [P11](#p11-fees-levied-and-legal-fees). |
| Regulation 35(f)(iii) interest accrued | Both figures exist and neither is chosen | [P12](#p12-interest-accrued-cell). |
| Regulation 35(f)(vii) legal fees | `legal_fees_cents is None` | No ledger bucket was copied onto the section. |
| Regulation 35(g) one running total | No field | The running figure is per bucket. |
| Logo | No field | [P1](#p1-which-logo). |

## 4. Field mapping

"Paint" means the stored field is placed in that cell. "Blank" means the cell is left empty for the reason in section 3.5. This layer does not fill a blank from the ledger.

### 4.1 Regulation 35(a) — credit provider

| Field | Painted from |
| --- | --- |
| (a)(i) name | `StoredStatement.legal_name` |
| (a)(ii) trading name, if any | `StoredStatement.trading_name`, omitted when blank |
| (a)(iii) NCR registration number | `StoredStatement.ncr_registration_number` |
| (a)(iv) physical and postal address | `physical_address`, `postal_address` |
| (a)(v) telephone | `telephone` |
| (a)(vi) payment-account details | `bank_name`, `bank_account_number`, `branch_code`, `payment_reference` |

Those six were copied at issue from `ProviderCompliance` by `ComplianceStore.require` (locked decisions 15 and 21). Enigma is not read for them.

### 4.2 Regulation 35(b), (c), (d)

| Field | Painted from |
| --- | --- |
| (b)(i) consumer name | `LoanSection.frozen_full_name`, inside that loan's section |
| (b)(ii) reference | `LoanSection.loan_id` |
| (b)(iii) address | `LoanSection.frozen_service_address` |
| Identity number | `LoanSection.frozen_id_number`. Decision 16 freezes it. It is printed with the name and the service address. |
| (c) statement date | `StoredStatement.statement_date`. The Statements layer sets this equal to `period_end`. A different statement date is [P14](#p14-statement-date-and-period-end). |
| (d) period | `period_start` and `period_end` |

The address cell is the service address frozen at booking (locked decision 16 and this layer's instruction). Regulation 35(b)(iii) says "the consumer's address" and does not say "service address". The paint rule follows the lock. The wording difference is conflict C4 in [section 8](#8-conflicts). No current postal address is read.

### 4.3 Regulation 35(e) — per loan

| Field | Painted from |
| --- | --- |
| (e)(i) principal debt | `principal_debt_cents` |
| (e)(ii) annual rate | Blank cell. Beside it: `base_rate`, `discount_rate`, `discount_fallen_away`, `periodic_rate_in_force`, `nominal_annual_on_base`, `nominal_annual_on_effective`. A `None` nominal is left blank. It is not calculated here. |
| (e)(iii) instalment | `instalment_cents`, `instalment_due_on` |
| (e)(iv) frequency | `payment_frequency` |
| (e)(v) balance outstanding | Per-bucket `closing`. The single cell is blank. |
| (e)(vi) in arrears, and the amount | `open_default_episode` and `overdue`. The amount cell is blank. |
| Campaign | `base_rate` and `discount_rate`, both, including when the discount has fallen away |

`periodic_rate_in_force`, `nominal_annual_on_base`, and `nominal_annual_on_effective` are `None` together when the Statements layer did not annualise that section (the classification is not short-term or unsecured, or an unsecured snapshot still carries a discount). The base and the discount on the section are still printed. This layer does not annualise them itself.

### 4.4 Regulation 35(f) — per loan

| Field | Painted from |
| --- | --- |
| (f)(i) payments received | `payments_received_cents` |
| (f)(ii) fees levied | Blank. Initiation, service, and `additional_monthly` stay visible as their own buckets in the component table and in the transaction list. |
| (f)(iii) interest accrued | Blank. `interest_billed_cents` and `interest_memo_rands` are printed as two labelled lines. |
| (f)(iv) insurance costs levied | `insurance_levied_cents` |
| (f)(v) collection costs levied | `collection_levied_cents` |
| (f)(vi) default administration costs levied | `default_administration_levied_cents` |
| (f)(vii) legal fees incurred | Blank |

A mapped cents field of zero is printed as zero.

### 4.5 Regulation 35(g) — per loan

| Field | Painted from |
| --- | --- |
| (g)(i) opening | `opening`, captioned as the previous closing only when `opening_source` is `previous-closing` |
| (g)(ii) date | `TransactionView.value_date` |
| (g)(iii) description | `TransactionView.description` |
| (g)(iv) debit or credit | `debit_cents`, `credit_cents` |
| (g)(v) running balance | Per-bucket replay in section 3.4. No single running total. |
| (g)(vi) closing | `closing` |

### 4.6 Lines the regulation does not name

Printed from the stored section because the locked decisions require the components. They are not folded into a Form 26 total.

| Line | Stored field | Lock |
| --- | --- | --- |
| Each bucket opening and closing | `opening`, `closing` | Decisions 2, 4, 6, 7, 12 |
| Unbilled interest memo | `interest_memo_rands` | Decision 6. Not part of the instalment and not part of arrears. |
| Lay-by hold | `laybye_hold` opening and closing | Decision 4 |
| In-duplum clip | Not painted as a change to the cents | Decision 7. The clip stays off. |

VAT ex-amount and VAT amount are not fields on `LoanSection` or `TransactionView`. They are not reconstructed. See [P13](#p13-figures-the-stored-section-does-not-carry).

## 5. Section 110 enquiry

The painting is the `AmountOwing` object `Documents.enquire` already returned. The painter does not call `enquire`. That method folds each day from disbursement through `request_on` and does not keep the result. A second call would touch the ledger again. See [P15](#p15-the-enquiry-is-not-stored).

The document is titled as an amount-owing enquiry. It is not titled as a periodic statement and it is not given an opening balance. It does not move the section 109 chain.

| Block | Painted from |
| --- | --- |
| Keys | `organisation_id`, `person_id`, `loan_id`, `request_on` |
| Deliver by | `deliver_by`. Already `add_business_days` for 10 business days, or 20 when the requested movement starts before the calendar anniversary of `request_on`. This layer does not count the days again. The anniversary reading of "one year" is the Statements layer's reading and is not a locked rule. |
| (a) current balance | One line per bucket in `components`. The single "current balance" cell is blank, for the same reason as [P8](#p8-single-balance-total). |
| (b) amounts credited or debited | `transactions`, in stored order, with the same date, description, debit, and credit columns as section 3.4. No opening line and no closing line are invented. An empty tuple means the request did not ask for a movement period. |
| (c) currently overdue | `overdue`: bucket, due date, cents. Due dates are already strictly before `request_on`. |
| (d) currently payable | `payable`: bucket, due date, cents. Due dates are already on or before `request_on`. |

Unbilled interest is not in `overdue` or `payable`. This layer does not add it.

Provider legal name, NCR number, addresses, telephone, payment-account details, and the frozen consumer name, identity number, and service address are not on `AmountOwing`. They are not filled by a configuration read at paint time. See [P16](#p16-letterhead-on-the-enquiry-and-the-quote).

## 6. Section 113 settlement quote

The painting is the `StoredQuote` object `Documents.settlement_quote` already returned. One quote, one loan. The periodic statement's one-document rule is not a combined settlement figure.

| Block | Painted from |
| --- | --- |
| Keys | `agreement_id`, `organisation_id`, `person_id` |
| Settlement date | `as_of` |
| Delivered on | `delivered_on` |
| Binds until | `valid_until`. This is the engine's `binding_until` result: five business days after delivery. The delivery date counts as a valid payment date. This layer does not count the days again. |
| Deliver by | `deliver_by`. Five business days after `request_on`. It is a different count from `valid_until`, and both are printed. |
| Unpaid principal | `principal_cents`. Gross of any lay-by hold (locked decision 4). |
| Unpaid interest | `interest_cents` |
| Unpaid fees | `fee_cents`, with `components` naming the buckets |
| Early-termination charge | `early_termination_cents`. Day-1 stores `0`. The painter prints that stored zero. It does not call `early_termination_ceiling_cents`. If the stored charge is not zero, the PDF is refused. |
| Settlement amount | `total_cents`. The painter does not add the components to produce a second total. If `principal_cents + interest_cents + fee_cents + early_termination_cents` does not equal `total_cents`, the PDF is refused. The stored total is not replaced. |
| Agreement size | `agreement_size`, the stored token `small` or `intermediate`. The same quote layout is used for both. A separate intermediate artwork is [P5](#p5-intermediate-agreement-artwork). A large agreement is not stored by this path. |

The Statements layer already refused a non-zero early-termination charge (`early-termination-unexpected`) and already checked `valid_until` against `binding_until`. This layer does not repeat those calculations. It also does not call `execute_settlement`.

The same letterhead gap as the enquiry applies: `StoredQuote` does not carry provider compliance or the frozen consumer identity ([P16](#p16-letterhead-on-the-enquiry-and-the-quote)).

Oral or written delivery is not a field on `StoredQuote` or `AmountOwing`. No channel mark is invented ([P17](#p17-oral-or-written-channel)).

## 7. Sequence of calls

Money, rates, business days, and the section 109 chain are already inside the objects below. The painter does not call the functions that produced them.

### 7.1 What the Statements layer already did

Recorded so this layer does not do it again. Citations are the locked sections those calls already implement.

```
Documents.issue_statement(organisation_id, person_id, period_start, period_end,
                           interest_cap_present, vat_rate, receipts)
  Servicing.enigma.check(organisation, person, "statement.issue")     §15
  on a repeat of the same period key: return the stored statement
      no ComplianceStore read, no ledger fold
  on the first issue only:
      ComplianceStore.require(organisation_id)                         §15 §21
          legal name, NCR number, trading name, addresses,
          telephone, payment-account details
      fold the period through Ledger and Servicing                    Layer 1
      opening = previous stored closing, per loan, per bucket         §12
      nominal_annual_rate(periodic, periods_per_year)                 §17
      campaign base and discount both kept                            §3
      Ledger.issue_statement(...)
      freeze StoredStatement, including pdf_stub which is not a PDF

Documents.enquire(...)
  folds the ledger through request_on
  does not call Ledger.issue_statement
  does not store the AmountOwing
  deliver_by = add_business_days(request_on, 10 or 20, holidays)

Documents.settlement_quote(agreement_id, as_of, delivered_on, request_on, holidays, vat_rate)
  Servicing.enigma.check(..., "settlement.quote")                      §15
  on a repeat of (agreement_id, as_of, delivered_on): return the stored quote
  on the first quote only:
      quote_settlement(...)                                            engine
      early_termination_cents must be 0, else the quote is refused
      valid_until must equal binding_until(delivered_on, holidays)
      deliver_by = add_business_days(request_on, 5, holidays)
      store StoredQuote
```

`ComplianceStore.require` is the configuration read for provider identity. It is part of issue, not part of painting. `cfg_brand` is not read on that path.

### 7.2 Paint a periodic statement

```
input: StoredStatement already returned by Documents.issue_statement

do not call Documents.issue_statement to create the statement
do not call ComplianceStore.require or ComplianceStore.find
do not read lms.cfg_brand
do not call the ledger or the engine

paint section 3 from the stored fields
replay section 3.4 from stored opening and stored lines
if any bucket replay != stored closing: produce no PDF
do not write pdf_sha256
do not deliver pdf_stub
```

A caller that no longer holds the object may call `Documents.issue_statement` again with the same organisation, person, and period only while that same `Documents` instance still has the statement in `Documents.statements`. The method runs the mandate check, then returns the stored statement and does not fold and does not read configuration. `interest_cap_present`, `vat_rate`, and `receipts` on that repeat do not change the stored figures. That repeat is a Statements-layer read of the in-memory cache. It is not available by `statement_id`, and it is not a read of `lms.client_statement`. See [P18](#p18-no-read-by-statement-id) and [P19](#p19-the-durable-row-is-not-the-paintable-record).

If that cache does not hold the period key, `issue_statement` folds the ledger. That is statement issue. This layer does not start it. A new `Documents` instance does not see a statement issued by another instance.

### 7.3 Paint a section 110 enquiry

```
input: AmountOwing already returned by Documents.enquire

do not call Documents.enquire
do not call ComplianceStore
do not call Ledger.issue_statement
do not give the document an opening balance

paint section 5 from the returned fields
```

### 7.4 Paint a section 113 quote

```
input: StoredQuote already returned by Documents.settlement_quote

do not call quote_settlement, binding_until, or add_business_days
do not call early_termination_ceiling_cents
do not call execute_settlement
do not call ComplianceStore

if early_termination_cents != 0: produce no PDF
if principal + interest + fee + early_termination != total: produce no PDF
paint section 6 from the stored fields
```

A repeat of `settlement_quote` with the same agreement, `as_of`, and `delivered_on` runs the mandate check and then returns the stored quote, while that same `Documents` instance still holds it. It does not reprice. There is no read by a quote id, and `lms.client_statement` does not store the quote ([P18](#p18-no-read-by-statement-id), [P19](#p19-the-durable-row-is-not-the-paintable-record)).

### 7.5 Calls this layer does not make

| Not called at paint time | Why |
| --- | --- |
| `ComplianceStore.require` | The statement already holds the copy. A later `put` must not rewrite it. The enquiry and the quote do not carry the copy; filling them from a live read is [P16](#p16-letterhead-on-the-enquiry-and-the-quote). |
| `lms.cfg_brand` | No reader, no copied logo key, and no locked choice among brand rows ([P1](#p1-which-logo)). |
| `cfg_brand.display_name`, `support_phone`, `support_email`, `statement_footer` | Branding is the logo only. |
| `nominal_annual_rate`, `periods_per_year`, `campaign_rate` | The stored nominals are the disclosure. Multiplying again would be a second implementation of decision 17. |
| `Ledger.bucket_balance` and every other ledger method | The opening, closing, and lines are already stored. |
| `quote_settlement`, `early_termination_ceiling_cents`, `execute_settlement` | The quote is already stored, the day-1 charge is the stored zero, and posting the settlement is not this document. |
| `add_business_days`, `binding_until` | `deliver_by` and `valid_until` are already stored. |
| `resolve_customer_settings` | Elections on the statement are the booking snapshot, already applied before the figures were stored (locked decision 19). |
| Enigma, including any live name or address | Consumer name, identity number, and service address are the frozen section fields (locked decision 16). Provider fields are the compliance copy. |
| `Servicing.issue_statement` | That path is not the Statements-layer issue this PDF paints. |

## 8. Conflicts

These are disagreements between the locked file, an earlier design, and the code this draft paints. This draft does not resolve them.

| # | What conflicts | What this draft does |
| --- | --- | --- |
| C1 | The comment on `lms.cfg_organisation_settings`, and `docs/lms-owned-configuration.md`, still say the LMS does not store the legal name or the NCR number and that those are read from Enigma. Locked decisions 15 and 21 say Enigma does not hold the NCR number, trading name, addresses, telephone, payment-account details, or brand assets, and that the LMS does. | Paint the compliance copy already on `StoredStatement`. Do not read Enigma. Do not edit the comment. The statements implementation note still describes this as an open conflict with decision 15; on the current locked file the configuration read is the locked source. |
| C2 | `docs/servicing/primary-flows.md` says brand colour and the logo are the white-label variation, and that intermediate agreements use this same document because that choice meets section 109(3). Neither sentence is in the locked file. The instruction for this layer is that branding is the logo only. | Paint no brand colour, no display name, and no logo until [P1](#p1-which-logo) is locked. Do not adopt the intermediate artwork. [P5](#p5-intermediate-agreement-artwork). |
| C3 | Two public transcriptions of regulation 35 disagree on "Form 26 or" versus "Form 26 and", and on whether item (g)(i) is the previous closing or the previous opening. The Statements layer recorded this and did not choose the gazette sentence. | Paint `LoanSection.opening`. Caption it as the previous closing only when `opening_source` is `previous-closing`. Section 109(1) and locked decision 12 fix that number. The gazette sentence stays unchosen ([P4](#p4-form-26-artwork-and-the-regulation-35-transcription)). |
| C4 | Regulation 35(b)(iii) says "the consumer's address". Locked decision 16 freezes the service address at booking, and this layer is instructed to use that frozen address. | Paint `frozen_service_address`. Do not read a current postal address. |
| C5 | `StoredStatement.pdf_stub` begins with `PDF-STUB` and `pdf_sha256` hashes those bytes. A PDF painting is a different byte string. | Do not deliver the stub. Do not overwrite the hash ([P3](#p3-the-stored-hash-is-the-stub)). |
| C6 | The Layer 1 design says a written section 110 enquiry is stored. `Documents.enquire` returns `AmountOwing` and does not store it, and it folds the ledger on every call. | Paint the returned object once. Do not call `enquire` from the painter ([P15](#p15-the-enquiry-is-not-stored)). |
| C7 | The Layer 1 design copies a logo key onto the statement at issue. `StoredStatement` has no logo field, and `issue_statement` does not read `cfg_brand`. | Leave the logo position empty ([P1](#p1-which-logo)). |
| C8 | The Layer 1 field list says regulation 35(f)(i) includes a reversal of a payment. `payments_received_cents` sums lines whose `kind` is `payment` and whose bucket is an owing bucket. A `reversal` line is not in that sum. | Paint `payments_received_cents` as stored. The reversal stays in the transaction list. This layer does not add it into the cell. |

## 9. Gaps that need a locked decision

None of these is given a value. The PDF leaves the affected cell blank, or it is not produced, as the section cited next to the gap says.

### P1. Which logo

`lms.cfg_brand` is keyed by `(organisation_id, brand_code)`. Its columns are `display_name`, `support_phone`, `support_email`, `logo_object_key`, and `statement_footer`. There is no Python reader. The booking record does not store a `brand_code`. `StoredStatement` does not store a logo key.

Locked decisions 15 and 21 say brand assets are LMS-owned. They do not say which row is the statement logo when several exist, or whether a missing logo blocks the document. Branding on these documents is the logo only, so the other four columns would not be painted even after a row is chosen.

This draft does not read `cfg_brand` at paint time. A live read would not be a stored figure, and a later brand edit would change a statement already issued. Zero rows, one row, and several rows are all left unpainted. The logo position stays empty.

### P2. First statement opening

Locked decision 12 chains each later opening to the previous stored closing. It does not say what the first opening is. The Statements layer stores the ledger balance on the day before `period_start` and labels it `no-previous-statement`. This layer prints that stored figure and that token. It does not relabel it as a previous closing.

### P3. The stored hash is the stub

`pdf_sha256` hashes `PDF-STUB` plus a partial JSON payload, not PDF bytes. No locked rule says when a real painting's hash replaces that value, or whether a later painting that hashes differently is rejected. This layer does not write the hash and does not deliver the stub.

### P4. Form 26 artwork and the regulation 35 transcription

Section 109(2) requires the prescribed form for a small agreement. This draft maps the regulation 35 fields. It does not redraw the gazette form. The "Form 26 or" / "Form 26 and" transcription, and the (g)(i) opening versus closing wording, stay unresolved (conflict C3). The number that is painted is the stored opening.

### P5. Intermediate-agreement artwork

Section 109(3) lets an intermediate or large agreement use the prescribed form or a provider form that meets the prescribed requirements. Day-1 unsecured loans can be intermediate and still sit under R250 000. `LoanSection` does not store `agreement_size` or classification. `principal_debt_cents` is cash advanced plus capitalised initiation, which is not the input `agreement_size` uses, so this layer does not classify the section by that figure.

`StoredQuote.agreement_size` is `small` or `intermediate`. The quote PDF uses one layout for both. No second artwork is specified. A large agreement is not given a quote and is not given an early-termination charge. The earlier servicing note that adopts the small-agreement form for intermediate agreements is not a locked decision (conflict C2).

### P6. Non-NCA sections on the same document

Locked decision 12 puts every loan of that client at that organisation on the one statement, including a zero-cost plan and a lay-by child. Form 26 is the small-agreement form. The locked file does not say whether those sections are painted as Form 26. This layer uses the same section order for every loan and does not title the page as Form 26.

### P7. Frozen identity differs across loans

Decision 16 freezes name, identity number, and service address on each loan. A later booking can freeze a different name. Regulation 35(b)(i) is one consumer name on the document. No rule picks among the frozen names. Each section keeps the identity stored on that section. No document-level name is printed.

### P8. Single balance total

Decisions 2, 4, 6, 7, and 12 constrain the components. They do not state one opening or closing figure, and they do not say whether unbilled interest and the lay-by hold sit inside it. The periodic statement and the section 110 "current balance" cell stay blank. Per-bucket figures are printed. No client-level sum is printed.

### P9. Which periodic rate fills the Form 26 cell

Locked decision 17: annual-equivalent rate = periodic rate × number of periods per year, simple nominal, not effective. Both the periodic rate and the nominal annual rate are disclosed. Locked decision 3: the base rate and the campaign discount are both shown, including after the discount falls away.

The Statements layer already stores `nominal_annual_on_base` and `nominal_annual_on_effective`, each labelled. `annual_rate_cell` is `None`. This layer prints the labelled pair and leaves the single cell blank. It does not choose the base, the rate in force, or a blend.

### P10. Arrears amount

Regulation 35(e)(vi) asks whether the account is in arrears and for the amount. Decisions 6 and 8 say a shortfall against the contractual instalment becomes arrears. They do not define the cents. The episode flag and the overdue rows are printed. `arrears_cents` stays blank.

### P11. Fees levied and legal fees

`fees_levied_cents` adds initiation, service, and `additional_monthly`. `additional_monthly` has no regulation 35 line of its own. Legal fees are regulation 35(f)(vii) and `legal_fees_cents` is `None`. Neither is merged into another line. The two Form 26 cells stay blank. The bucket rows and the transaction lines still show the posted cents.

### P12. Interest accrued cell

Regulation 35(f)(iii) says "interest accrued". The section stores `interest_billed_cents` and `interest_memo_rands`. Decision 6 excludes unbilled interest until it is debited. The cell stays blank. Both labelled figures are printed. They are not added.

### P13. Figures the stored section does not carry

The Layer 1 field list names an ex-VAT / VAT split and an in-duplum ceiling and accrued counter. `LoanSection` and `TransactionView` do not carry them. `vat_on_rand_maxima` remains on the booking snapshot, which is not copied onto the section. This layer does not read the ledger to recover them, and it does not invent the cents. Decision 9's split and decision 7's ceiling are therefore not on the PDF until they are part of the stored statement.

### P14. Statement date and period end

`statement_date` is stored as `period_end`. Regulation 35(c) and (d) are separate fields. This layer prints the stored date. It does not invent a second one.

### P15. The enquiry is not stored

`Documents.enquire` returns `AmountOwing` and does not keep it. Every call folds the ledger from disbursement through `request_on`. A paint that called `enquire` would not be a painting of stored figures. The painter accepts the object it was given and does not call `enquire`. Section 110(4) excuses are not applied by the Statements layer; this layer does not add them.

### P16. Letterhead on the enquiry and the quote

`StoredStatement` carries the compliance copy and, on each loan, the frozen consumer identity. `AmountOwing` and `StoredQuote` carry neither. Painting a provider block or a consumer block on those two documents would be a new read of `ComplianceStore` or of the loan, at paint time, and a later compliance edit would change the document. This layer does not do that read. The money, dates, and movement lines that are on the object are painted. The letterhead is not.

### P17. Oral or written channel

Section 110(3) and section 113(2)(b) follow the consumer's direction, to the extent the provider is equipped. Neither result object stores a channel. No mark is printed.

### P18. No read by statement id

`Documents.statements` is an in-memory dict keyed by `(organisation_id, person_id, period_start, period_end)`. `Documents.quotes` is an in-memory dict keyed by `(agreement_id, as_of, delivered_on)`. There is no method that returns a stored statement or quote by its id without the issue or quote arguments. A repeat of `issue_statement` or `settlement_quote` still runs the Enigma mandate check before it returns the stored object, and only when that same instance still holds the cache entry. This layer does not add a reader. A suspended enrolment or an Enigma timeout on that repeat fails closed under decision 15, including when the figures were stored earlier on that instance.

### P19. The durable row is not the paintable record

`lms.client_statement` stores the organisation, statement id, person, and period. `lms.client_statement_balance` stores per-loan, per-bucket opening and closing cents. `Documents.issue_statement` does not insert those rows. The regulation 35 fields, the frozen consumer identity, the provider compliance copy, the rates, the transaction lines, and the enquiry and quote are not columns on those tables. They live on the `StoredStatement`, `AmountOwing`, or `StoredQuote` value in memory.

Painting from `client_statement` would drop every field those tables do not hold. This layer does not add a write and does not reconstruct the missing fields from the ledger. The PDF is painted from the object the Statements layer returned.

## 10. Out of scope

- Production code, a PDF library, fonts, page size, and delivery transport.
- Replacing `pdf_stub` or `pdf_sha256`.
- Section 111 disputes and section 112 adjustments.
- Posting `execute_settlement`.
- The section 125(2)(c) early-termination formula. The painted day-1 charge is the stored zero.
- A section 104 notice (locked decision 11). The rate on the statement is the rate already stored.
- Credit-life statements held by the insurer (locked decision 4).
- Choosing Form 26 artwork, an intermediate artwork, or a logo row.
- Writing `lms.client_statement` or adding the regulation 35 columns it does not have.
