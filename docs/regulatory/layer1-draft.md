# Regulatory extracts — Layer 1 draft

**Status: Layer 1 draft. Design only. This file is not production code and it is not a locked decision.**

`docs/LOCKED_DECISIONS.md` on `main` (last updated 2026-10-28) is the source of truth. This draft calls the Layer 0 interfaces. It does not re-implement their formulas, journals, caps, or elections.

Layer 0 was read from these branches. They are not merged to `main`. Where a branch copy of the locked file differs from `main`, `main` wins. That difference is RX43.

| Layer | Branch read | Surface this draft calls |
| --- | --- | --- |
| Calculation engine | `cursor/day1-calc-engine-928f`, as included on `cursor/layer0-smoke-4153` | `lms.calc` is not called. Caps stay where they were applied at posting. |
| Configuration | `cursor/lms-owned-config-1a86`, as included on the smoke branch | `lms_config`, `lms.cfg_*`, `lms.ref_*`, `lms.audit_event` |
| Ledger | `cursor/ledger-account-model-7aa6`, as included on the smoke branch | `lms.ledger` |
| Servicing orchestration | `cursor/servicing-orchestration-9c3c`, as included on the smoke branch | `lms.servicing` records already written. This draft does not book, disburse, or post. |
| Enigma port | `cursor/enigma-interface-d0c7` | `ncr_number_required`, `OrganisationContext`, `AgreementIdentity`. The port is a sketch. Its NCR store conflicts with the configuration note. See RX22. |

The smoke-branch copy of the locked file is behind `main`. It still says memo accruals are not allocatable, and it does not contain the current section 1 sentence that capitalises the day's due amounts before that day's receipts, or the current section 8 sentences on NCA limits, arrears, and the residual write-off. The interfaces below were built against that older copy. This draft follows `main`.

## 1. What this layer owns

Regulatory extracts is a read layer. It assembles three files from facts Layer 0 has already stored. It does not accrue, bill, allocate, reverse, flag default, or clip.

Three extracts are in scope:

1. SACRRA submission, under regulation 19(13) and the NCR guideline that prescribes the SACRRA L700v2 layout.
2. NCR Form 39 readiness, under regulation 64.
3. The financial and operational audit log, including the hash chain.

A fourth section records the compliance boundaries the task sets on top of the locked file: NCA fee and interest limits, the NCR number on NCA communications, and the identity freeze.

Transmission is out of this draft. The SACRRA overview names the Data Transmission Hub as the prescribed channel. This draft stops at the extract rows. It does not open a hub session, and it does not submit Form 39 to the Regulator.

## 2. Locked rules this draft applies

Citations only. The text of the rule stays in the locked file.

| Topic | Lock | What this draft does with it |
| --- | --- | --- |
| Value date | §1 | An as-of date and a filter date are Johannesburg calendar dates. 00:00 that day is `value_instant`. Same-day postings keep the recognition sequence they already have. A reversal keeps the original value date, so a later reversal changes an earlier as-of sum. See RX10. |
| Same-day order | §1 | Capitalise the day's due amounts, then allocate that day's receipts. The extract does not run that order. It reads balances after Layer 0 has posted it. See RX9. |
| Initiation | §2 | Day-1 short-term and unsecured keep the initiation fee non-capitalised. `capitalised_initiation_cents` is there for the column. On a Day-1 agreement it is zero because booking refuses capitalisation. |
| Zero rates | §3 | A zero rate or a zero fee still produces a row. A zero does not drop the agreement from the file. |
| Lay-by pair | §4 | One agreement. One SACRRA row, on the parent. The hold is not a second consumer account. Principal stays gross. The hold is its own bucket. |
| Day count | §5 | The method is the one on `ElectionSnapshot`. The extract does not accrue, so it does not choose a day count. |
| Default | §6 | One test, already applied by `Ledger.flag_default`. The extract reads an open `Episode`. It does not run a second days-past-due test. Unbilled interest is a memo until `bill_interest` posts it. |
| In duplum | §7 | The episode ceiling is stored. The clip is off. Reported interest and fees are the posted cents, including amounts above `ceiling_cents`. |
| NCA limits | §8 | Fees and interest charged are the posted charges. The extract does not apply a second cap. |
| Allocation | §8 | Section 126 order stays in the ledger. The extract does not allocate. |
| Service fee | §9 | The posted service-fee charge, with `ex_vat_cents` and `vat_cents`, is the charged fee. The R60 cap was applied when `levy_service_fee` ran. |
| Statements | §12 | One statement per client per organisation, with each loan's own balances. SACRRA grain is the agreement, not that combined statement. |
| Instalment | §13 | The contractual instalment the client accepted is binding. It is not stored as one column. See RX18. |
| Frequencies | §14 | `weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual`. The L700 numeric frequency code is a separate vocabulary. See RX19. |
| Enigma | §15 | Opaque `person_id` and `organisation_id`. Timeout, an ambiguous status, or a clear suspended enrolment fails closed. The extract does not invent a mandate action. See RX40. |
| Identity freeze | §16 | Name, ID number, and service address come from the agreement. A later Enigma read does not rewrite them. |
| Rounding | §17 | Posted cents are already half-up. The extract does not round again. |
| Tariffs | §18 | A missing tariff fails the levy. The extract does not look up a tariff to change a posted charge. |
| Elections | §19 | An open agreement is read from `ElectionSnapshot`. `resolve_customer_settings` is not called again. |

## 3. Conflicts raised before any field is filled

These are conflicts between this task, the locked file, and designs that are already on other branches. This draft does not pick a winner.

### 3.1 Where the NCR number lives (RX22)

Three readings are already written, and none of them is a locked rule.

| Reading | Where it is written | What it says |
| --- | --- | --- |
| Configuration note | `docs/lms-owned-configuration.md` on the smoke branch | The organisation's legal name and NCR number are Enigma's. Origination copies the number onto `AgreementPin.ncr_registration_number`. Configuration has nowhere to type a competing number. The copy is not one of the three fields §16 freezes. |
| Servicing flows | `docs/servicing/primary-flows.md` on the smoke branch | `get_organisation` returns `legal_name` and `ncr_registration_number` from Enigma. The statement prints them. |
| Enigma port | `docs/enigma/lms-enigma-interface.md` port decision 4, conflict C2 | Enigma does not hold the NCR number. LMS stores it as a tenant regulatory attribute. A blank number blocks an NCA communication or extract and does not block booking. |
| Locked file | §15 | LMS stores opaque `person_id` and `organisation_id` and does not re-implement organisation identity. The NCR number is not in the list of frozen fields in §16. |

`AgreementPin.ncr_registration_number` is a dataclass in `lms_config.context`. The comment above `SHORT_TERM_ORDINAL_SQL` says the pin table is not in the migration. `LoanAccount`, `lms.loan_account`, and `AgreementRecord` have no NCR column. `EnigmaStub.check` returns `full_name`, `id_number`, `service_address`, and `enrolment_id`. `OrganisationContext` on the Enigma port returns `legal_name` and `trading_name` and no NCR number. No interface this draft can call returns the number today (RX25).

### 3.2 Two product vocabularies (RX24)

The Enigma port gate is `ncr_number_required(product_code, pure_hosting)` in `src/lms/enigma/regulatory.py`.

| Port code | Port meaning | NCR number on an NCA communication or extract |
| --- | --- | --- |
| `lms.micro_short_term` | Micro / short-term | Required unless the tenant is pure hosting |
| `lms.unsecured_personal` | Unsecured personal | Required unless the tenant is pure hosting |
| `lms.bnpl_laybye` | BNPL / lay-by, zero cost | Not required |
| `lms.laybye_security` | Lay-by as zero-interest security or deposit | Not required |
| Any other non-null code | Unclassified | Required. The function does not treat an unknown code as exempt. |
| `pure_hosting` true, or a null product code | Hosting, or no product | Not required |

The ledger classification vocabulary is different: `short_term`, `unsecured`, `zero_cost`, `cpa_layby`. `ProductTerms` has `classification` and no Enigma product code. `lms.cfg_product.enigma_enrolment_code` exists on the product row. The booked `lms.loan_account` row does not point at that product. This draft does not treat `short_term` as `lms.micro_short_term`, and it does not treat `zero_cost` or `cpa_layby` as `lms.bnpl_laybye`.

`pure_hosting` is an argument of the gate. `lms.cfg_organisation_settings` has no such column (RX23). An unset flag is not read as false, because false would demand an NCR number, and it is not read as true, because true would drop the demand. The gate is not called until both inputs exist.

### 3.3 What "micro" means

The task says the NCR number is required for micro and unsecured personal. The locked file uses the regulation 39 word `short_term`. The port uses `lms.micro_short_term`. Equating those three strings is RX24, not a locked decision.

## 4. Point-in-time balances

One balance rule is used by the SACRRA snapshot and by the Form 39 debtors book. It is the ledger's rule.

`Ledger.bucket_balance(account, bucket, as_of=D)` sums entries whose transaction `value_date` is on or before `D`. `D` is a Johannesburg date. Debit-normal buckets are `principal`, `interest`, `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, and `additional_monthly`. `laybye_hold` is credit-normal and is not subtracted from that sum. §4 keeps principal gross for settlement. The hold reduces the interest base inside the ledger. It does not reduce the balance the consumer owes.

`accrue_day` posts an `interest_accrual` with `entries=()` and a `memo_rands` amount. That memo is outside `bucket_balance`. §6 excludes unbilled interest until it is debited. `bill_interest` is the debit. A balance therefore includes interest only after that bill.

The extract does not call `accrue_day`, `bill_interest`, `levy_service_fee`, `levy_charge`, or `post_payment` in order to make `D` complete. §1 requires the day's due amounts to be capitalised before that day's receipts are allocated. §8 allows capitalisation on a later calendar day than the payment. There is no stored marker that the day's accrual has run (RX9). The read that exists today is the sum of what has already been posted.

`Ledger.statement` is not the balance source. Its opening and closing maps, in the current method, contain `principal`, `interest`, and `laybye_hold` only. Fee buckets would disappear from a file built on that map. The extract calls `bucket_balance` once per bucket.

### 4.1 Later reversals

§1 gives a reversal the value date of the original recognition. `bucket_balance` then changes for every as-of date on or after that value date, including a month that was already extracted. The store keeps `recognised_at` and `value_date` on the same transaction. A transaction with `value_date <= D` and `value_date(recognised_at) > D` is a restatement of `D`.

No table stores a submitted SACRRA or Form 39 file. This draft does not invent a second balance that ignores the reversal. When such a transaction exists, the extract stops with `balance-restated` and emits no file (RX10).

### 4.2 Which agreements

`LedgerStore.accounts_for(organisation_id)` returns the tenant's accounts. Rows with `instrument_kind == "laybye_hold"` are children. They are read only to report the parent's hold bucket. They are not their own SACRRA account and not their own Form 39 account (§4).

`organisation_id` on the ledger is `text`. `organisation_id` on `lms.cfg_organisation_settings` and `lms.audit_event` is `uuid`. The ledger migration records that difference as unresolved. This draft does not cast one to the other (RX39). A call passes the identifier the target interface already stores.

## 5. SACRRA extracts

### 5.1 Authority for the field list

Regulation 19(13) requires a credit provider to submit credit information in the manner and form the NCR prescribes. The NCR guideline, read here through the SACRRA overview *Reporting of Credit Information in terms of Regulation 19(13)* (sacrra.org.za, the L700v2 pages), prescribes the SACRRA data specification L700v2 and the Data Transmission Hub.

That overview states:

- A monthly file and a daily file are both required.
- The monthly file is a snapshot at month-end or at an agreed billing date, described as the same information that would be on a statement.
- The daily file is for accounts opened and closed.
- The monthly layout in the overview is 56 fields, positions 1–700, plus a header and a footer.
- The daily layout is described as 58 fields. The two extra fields are not in the overview.
- The full specification is described as about 300 pages and 930 validation rules. Those pages are not in this repository.
- Balances and mandatory details must be up to date at the time of the extract.
- Demographic and financial fields are each mandatory, optional, or conditional under the full specification. The overview's worked examples of that split are surname (mandatory), employer detail (optional), and a passport number together with a date of birth (conditional).

The March 2024 amendment to the guideline (Annexure A, as fetched from the NCR) names account-type codes. Two fetched copies disagree on code `L` (one says life insurance, another says handed over). This draft does not use code `L`. It also does not choose among `M` (one-month personal loan), `P` (personal loan with a term greater than one month), and `I` (instalment) for a Day-1 agreement (RX5).

The overview does not state the submission calendar beyond "agreed timelines". No day-of-month is introduced here (RX2). The as-of date is an argument. Month-end and the statement billing date are both allowed by the overview, and §12 says the statement period bounds are not locked. This draft does not choose between them (RX1).

### 5.2 Frequency

| File | When this draft will emit it | Grain |
| --- | --- | --- |
| Monthly L700v2 | Caller supplies one Johannesburg as-of date `D`. One row per parent loan that has a `disbursement_value_date` on or before `D`. | The parent agreement |
| Daily L700v2 | Caller supplies one Johannesburg date. Opened rows are parents whose `disbursement_value_date` is that date. | The parent agreement |

A pending agreement (`AgreementRecord.status == "pending_disbursement"`, no ledger loan yet) has no disbursement value date. It is not an opened account.

Closed rows need the date the agreement became `settled`, `early_settled`, `written_off`, `cancelled`, or `rescinded`. `lms.loan_account` has no status and no closed-on date. `AgreementRecord.status` has no effective date. `AGREEMENT_STATUS_CHANGED` is a seeded audit type, and nothing in `src/lms` inserts `lms.audit_event` (RX49, RX41). The daily file's closure half stops with `closure-date-unset`.

The 58-field daily layout, the header, and the footer are not transcribed. A file that needs them stops with `layout-incomplete` (RX3). The 56-field monthly body is mapped below. No L700 file is emitted while RX3 leaves the mandatory set unknown.

### 5.3 Monthly field map

Positions and formats are the overview's monthly example. "Source" is the Layer 0 fact. "Emit" is what this draft will put in the file before the gaps in section 11 are locked. An unset emit means the column is left empty and a file that the full specification marks mandatory stops, rather than carrying a guessed code or a zero.

| No. | L700 name | Pos. | Format | Source | Emit |
| --- | --- | --- | --- | --- | --- |
| 1 | DATA | 1 | A 1 | Record-type marker in the layout. The overview does not give the character. | Unset (RX3) |
| 2 | SA ID NUMBER | 2–14 | N 13 | `LoanAccount.frozen_id_number`, frozen at booking (§16) | Unset until the frozen value is known to be a 13-digit SA ID (RX12) |
| 3 | NON-SA ID NUMBER | 15–30 | A 16 | The same frozen field. The column does not say which kind of identifier it is. | Unset (RX12) |
| 4 | GENDER | 31 | A 1 | No column | Unset. The ID number is not decoded (RX12) |
| 5 | DATE OF BIRTH | 32–39 | N 8 | No column | Unset. The ID number is not decoded (RX12) |
| 6 | BRANCH CODE | 40–47 | A 8 | No column. `cfg_brand` is presentation. | Unset (RX15) |
| 7 | ACCOUNT NO. | 48–72 | A 25 | `LoanAccount.loan_id` | The loan id, truncated only if a later lock defines the 25-character rule. No truncation is applied in this draft (RX3) |
| 8 | SUB-ACCOUNT NO. | 73–76 | A 4 | The lay-by child is not a sub-account (§4) | Unset (RX16) |
| 9 | SURNAME | 77–101 | A 25 | `frozen_full_name` is one string | Unset. The string is not split (RX11) |
| 10 | TITLE | 102–106 | A 5 | No column | Unset |
| 11 | FORENAME OR INITIAL 1 | 107–120 | A 14 | `frozen_full_name` | Unset (RX11) |
| 12 | FORENAME OR INITIAL 2 | 121–134 | A 14 | No column | Unset |
| 13 | FORENAME OR INITIAL 3 | 135–148 | A 14 | No column | Unset |
| 14–17 | RESIDENTIAL ADDRESS LINE 1–4 | 149–248 | A 25 each | `frozen_service_address` is one string | Unset. The string is not split into lines (RX13) |
| 18 | POSTAL CODE OF RESIDENTIAL ADDRESS | 249–254 | A 6 | No column | Unset (RX13) |
| 19 | OWNER / TENANT | 255 | A 1 | No column | Unset |
| 20–23 | POSTAL ADDRESS LINE 1–4 | 256–355 | A 25 each | No second address. §16 freezes the service address. | Unset (RX13) |
| 24 | POSTAL CODE OF POSTAL ADDRESS | 356–361 | A 6 | No column | Unset (RX13) |
| 25 | OWNERSHIP TYPE | 362–363 | A 2 | No column. The overview does not define the codes on the pages read. | Unset |
| 26 | LOAN REASON CODE | 364–365 | A 2 | No column | Unset |
| 27 | PAYMENT TYPE | 366–367 | A 2 | `payment_frequency` is a different fact. The overview does not define payment-type codes. | Unset (RX19) |
| 28 | TYPE OF ACCOUNT | 368–369 | A 2 | `ElectionSnapshot.classification` | Unset. No map from classification to `M`, `P`, or `I` (RX5) |
| 29 | DATE ACCOUNT OPENED | 370–377 | N 8 | `disbursement_value_date` | The date, once the N 8 digit order is locked (RX20). Booking date is a different column (`AgreementRecord.booking_value_date`) and is not this field. |
| 30 | DEFERRED PAYMENT DATE | 378–385 | N 8 | First `due_on` of the current `ScheduleVersion` | The date, once RX20 is locked. The overview does not define the field beyond its name. |
| 31 | DATE OF LAST PAYMENT | 386–393 | N 8 | Latest transaction with `kind == "payment"` and `value_date <= D`, excluding a payment whose `transaction_id` is some row's `reverses_transaction_id`. `Ledger.reverse` stamps that contra with the original value date. | The date, once RX20 is locked. `ordered_receipts` drops a payment that has no `attributed_due_on`, so it is not this date. |
| 32 | OPENING BALANCE / CREDIT LIMIT | 394–402 | N 9 | `cash_advanced_cents` and `capitalised_initiation_cents` | Unset. Which of those is the L700 figure is not locked. Day-1 has no credit limit (RX21) |
| 33 | CURRENT BALANCE | 403–411 | N 9 | Sum of the eight debit-normal buckets at `D`, section 4. The hold is not in that sum (§4). | Unset as an L700 amount until RX8 confirms this sum is the prescribed balance and RX50 locks the N 9 scale. The sum itself is available from `bucket_balance`. |
| 34 | CURRENT BALANCE INDICATOR | 412 | A 1 | Sign of that sum | Unset. The overview does not give the character (RX50) |
| 35 | AMOUNT OVERDUE | 413–421 | N 9 | Remaining cents on slices and charges with `due_on <= D` | Unset. That candidate is not locked as the SACRRA overdue amount. Unbilled memos stay out under §6 (RX7) |
| 36 | INSTALMENT AMOUNT | 422–430 | N 9 | No single stored instalment. Schedule lines are principal slices. | Unset (RX18) |
| 37 | MONTHS IN ARREARS | 431–432 | N 2 | An open `Episode` is the locked default. It is not a month count. | Unset. A zero is not written for "not in default" (RX6) |
| 38 | STATUS CODE | 433–434 | A 2 | `Episode`, and `AgreementRecord.status` where the servicing record still exists | Unset. Servicing statuses are not SACRRA codes (RX4) |
| 39 | REPAYMENT FREQUENCY | 435–436 | N 2 | `payment_frequency` | Unset. The token is stored. The numeric code is not (RX19) |
| 40 | TERMS | 437–440 | N 4 | Count of lines on the current schedule version | Unset. That count is a count of principal slices, and the overview does not define terms (RX18) |
| 41 | STATUS DATE | 441–448 | N 8 | `Episode.started_on` or `Episode.closed_on` when an episode exists | Unset together with field 38 (RX4) |
| 42 | OLD SUPPLIER BRANCH CODE | 449–456 | A 8 | No column | Unset (RX15) |
| 43 | OLD ACCOUNT NUMBER | 457–481 | A 25 | No column | Unset |
| 44 | OLD SUB-ACCOUNT NUMBER | 482–485 | A 4 | No column | Unset |
| 45 | OLD SUPPLIER REFERENCE NUMBER | 486–495 | A 10 | No column. The supplier reference itself is issued by SACRRA and is not stored. | Unset (RX15) |
| 46 | HOME TELEPHONE | 496–511 | A 16 | No column. Live Enigma `CommunicationPreferences` may hold a mobile, and §16 does not freeze it. | Unset. The extract does not read a live phone onto the agreement (RX14) |
| 47 | CELLULAR TELEPHONE | 512–527 | A 16 | Same | Unset (RX14) |
| 48 | WORK TELEPHONE | 528–543 | A 16 | No column | Unset |
| 49 | EMPLOYER DETAIL | 544–603 | A 60 | No column. The overview names this as an optional example. | Empty when the specification's optional rule is the one that applies. The full rule text is not in the repo (RX3, RX14) |
| 50 | INCOME | 604–612 | N 9 | No column | Unset (RX14) |
| 51 | INCOME FREQUENCY | 613 | A 1 | No column | Unset |
| 52 | OCCUPATION | 614–633 | A 20 | No column | Unset |
| 53 | THIRD PARTY NAME | 634–693 | A 60 | No sale command and no column | Unset (RX17) |
| 54 | ACCOUNT SOLD TO THIRD PARTY | 694–695 | N 2 | No sale command | Unset (RX17) |
| 55 | NO OF PARTICIPANTS IN JOINT LOAN | 696–698 | N 3 | One `person_id` on the account | Unset. A count of 1 is not written from that fact (RX16) |
| 56 | FILLER | 699–700 | A 2 | Layout | Spaces, once the overview's filler rule is confirmed (RX3) |

Header fields the overview names and does not lay out: supplier reference number issued by SACRRA, name of the credit or data provider, and the month-end or transaction date of the file (RX15, RX3). The provider name is Enigma `OrganisationContext.legal_name`, read live. It is not a §16 field. A timeout or an ambiguous organisation status fails closed (§15). `cfg_brand.display_name` is not the legal name.

### 5.4 What a monthly row can already show internally

The file in section 5.3 is the prescribed layout. Beside it, the ledger can already return these facts for agreement `loan_id` at date `D`. They are the inputs a later lock would map. They are not written into an L700 column by this draft.

| Internal fact | Call |
| --- | --- |
| Frozen name, ID number, service address | `LoanAccount` fields. No Enigma call. |
| Classification, frequency, rates, leniency, threshold, day count, VAT election, capitalisation flag | `LoanAccount.snapshot` |
| Cash advanced, capitalised initiation, disbursement date, contractual end | `LoanAccount` |
| Current bucket cents | `Ledger.bucket_balance` per bucket, `as_of=D` |
| Hold | `bucket_balance` on the child for `laybye_hold`, or the parent's hold entries |
| Open default | The `Episode` with `closed_on is None`. `started_on`, `ceiling_cents`, `accrued_cents` |
| Last payment value date | `LedgerStore.transactions_for`, kind `payment` |
| Schedule | Current `ScheduleVersion.lines` |

`is_in_default_at_morning_check` is not called. The episode is the result of the check that already ran.

## 6. NCR Form 39 readiness

### 6.1 Authority, and the limit of what was read

Regulation 64, as set out on the NCR compliance text for statutory reporting:

- A credit provider whose annual disbursements exceed R15 million, or per fee category, submits Form 39 for each quarter.
- Quarter 1 is 1 January–31 March, due 15 May.
- Quarter 2 is 1 April–30 June, due 15 August.
- Quarter 3 is 1 July–30 September, due 15 November.
- Quarter 4 is 1 October–31 December, due 15 February.
- Every other credit provider submits Form 39 by 15 February for 1 January–31 December.

The R15 million test, and the words "or per fee category", are not stored. This draft does not decide quarterly versus annual. The caller supplies the Johannesburg period start and period end (RX27).

The current Schedule 1 form image was not readable from the public page that hosts it. The field list below is taken from the draft form printed in Government Gazette 28531 of 20 February 2006, which is a draft published before the regulations of 31 May 2006, and from the glossary of the NCR Consumer Credit Market Report, which says it is compiled from Form 39 returns. The gazette OCR mixes Form 39 with later forms, including an insurer return under sections 16 and 106. That insurer return is not treated as Form 39. A filing layout waits on a field-by-field lock against the current prescribed form (RX26).

### 6.2 Header

| Element | Source | Stored today |
| --- | --- | --- |
| Name of registered entity | Enigma `OrganisationContext.legal_name`, live read | The port sketch has the field. The servicing stub does not. Fail closed on timeout or an ambiguous status (§15). Not frozen under §16. |
| NCR registration number | The unresolved store in section 3.1 | No |
| Start and end of the reporting period | Caller, Johannesburg dates | The period is an argument, not a row |
| Name and designation of the person who completed the form | No column | No |
| Email and contact telephone | No compliance-contact column. `cfg_brand.support_email` and `support_phone` are presentation. | No |
| Entity registration or CIPRO number, as labelled on the draft header | No column | No |

### 6.3 Agreements entered into during the period

The draft says section 1 is credit agreements entered into, and credit facilities utilised, during the quarter.

| Element | Candidate source | Stored today |
| --- | --- | --- |
| 1.1.1 Applications for credit received | A decision-engine fact. §13 says the LMS must accept external decisions. A rejected application never becomes a ledger row. | No (RX28) |
| 1.1.2 Applications rejected | Same | No (RX28) |
| 1.2.1 Rand value of credit agreements entered into | `cash_advanced_cents` on parents whose `disbursement_value_date` falls in the period. Booking date and cash-plus-capitalised-fee are different numbers. | The cents are stored. Which number the form wants is not locked (RX34) |
| 1.2.2 Number of credit agreements entered into | Count of those parents | The count can be formed once RX34 chooses the date |
| 1.2.3 Rand value of credit-facility transactions | Ledger `book` rejects `credit_facility` | The Day-1 book has no such row. The form line is left unset. A zero is not written (RX36) |
| 1.2.4 Number of credit-facility transactions | Same | Unset (RX36) |

`zero_cost` and `cpa_layby` are outside Table A. The configuration seed says a CPA lay-by is not an NCA credit agreement while no credit charge is levied, and that zero-cost BNPL is not priced under Table A. This draft does not add either classification into the short-term or unsecured lines (RX36).

### 6.4 Distribution lines on the draft

| Element | Source | Stored today |
| --- | --- | --- |
| Provincial rand value of agreements, nine provinces | A province on the consumer | No. The frozen service address is one string and is not parsed (RX29) |
| Provincial rand value of facility transactions | Same, and no facility book | No |
| Applications received from historically disadvantaged persons, and how many were rejected | Application facts plus a demographic | No (RX28, RX29) |
| Agreements with historically disadvantaged persons, number and rand | Demographic | No (RX29) |
| Agreements with low-income persons | An income amount and a locked definition of low income | No (RX30) |
| Agreements with women | Gender | No. The ID number is not decoded (RX29) |
| Agreements with juristic persons | `person_id` is opaque. Natural and juristic are not distinguished. | No (RX29) |
| Agreements with residents of rural or low-density areas | Address classification | No (RX29) |

The Consumer Credit Market Report publishes income bands such as "up to R10 000", "R10 001–R15 000", and "greater than R15 000" for several credit types. Those are publication bands of the report, not a locked reading of the form, and income is not stored. They are not used.

### 6.5 Debtors book on the last day of the period

The draft repeats this block. The market report's credit types are mortgages, secured credit, credit facilities, unsecured credit, short-term credit, and developmental credit. Day-1 `book` accepts `short_term`, `unsecured`, `zero_cost`, and `cpa_layby` only. Mortgage, facility, secured, and developmental lines stay unset (RX36).

The market-report glossary defines gross debtors book as the outstanding balances at the end of the period, including fees and interest that have been earned and capitalised. That sentence matches section 4 of this draft: billed bucket balances at the period-end value date, memos excluded. It is a glossary of the report, not yet a lock that the current form uses those words (RX26, RX31).

| Element | Source | Stored today |
| --- | --- | --- |
| Gross value on the last day | Sum of the eight debit-normal buckets at the period end, parents only, hold not subtracted | Yes, by the call in section 4, subject to RX9 and RX10 |
| Provision for doubtful debt | No balance | No (RX31) |
| Net value | Gross minus provision | Cannot be formed (RX31) |
| Number of accounts in the book | Parents in the sum. Closed accounts cannot be removed, because the closure date is unset. | Partial (RX49) |
| Rand value of write-offs during the period | `BALANCE_WRITTEN_OFF` is a seeded audit type. `Ledger` has no write-off method. | No (RX32) |
| Number of accounts written off | Same | No (RX32) |
| Age analysis: current, 30 days, 31–60, 61–90, 90–120, 120+, in rand and in number | The draft form's buckets | No. An open episode is not one of these buckets. No month count is computed (RX33) |

### 6.6 Annual pricing block

The draft says the pricing section is completed once a year for 1 January–31 December. The OCR shows, for several credit types, an initiation fee at stated principal amounts, and the lowest, highest, and average monthly service fee and interest rate inside size bands. The bands differ by page and are damaged in the OCR. They are not copied into this draft as the bands to use (RX35).

Two sources exist, and they answer different questions:

| Question | Source |
| --- | --- |
| What the published terms allow | `lms.cfg_product_terms`, `lms.cfg_fee_rule`, and the snapshot's `base_rate` and `discount_rate` |
| What was charged on agreements in the year | Posted `initiation`, `service`, and `interest` charges, `ex_vat_cents` and `vat_cents` |

The draft's phrase on the initiation line is about the fee that will be charged. This draft does not decide that the phrase means the tariff rather than the amounts levied (RX35). Neither set of figures is reduced to the statutory cap a second time. §8 was applied when the charge was posted. The cap rows (`ref_interest_cap`, `ref_initiation_fee_cap`, `ref_service_fee_cap`, and `ref_charge_rule` code `initiation_principal_ratio`) can be listed beside those figures for a reviewer. They do not replace them.

### 6.7 Elements the form needs that are not stored

Collected in one place. Detail is in section 11.

- NCR registration number (RX22, RX25).
- Applications received and rejected (RX28).
- Province, gender, historically disadvantaged person, woman, juristic person, rural or low-density resident, income, and the low-income threshold (RX29, RX30).
- Provision, and therefore the net book (RX31).
- Write-offs (RX32).
- Age-analysis buckets (RX33).
- The annual size bands and the choice between tariff and levied price (RX35).
- Compliance contact, email, telephone, and the entity's companies-register number (section 6.2).
- A locked copy of the current Form 39 cells (RX26).

## 7. Audit extract

### 7.1 What is read

`lms.audit_event` is the financial and operational log. The seal in `lms.seal_audit_event`, as replaced by migration `0003_elections.sql`, assigns `recognition_sequence` and the two hashes. The table is append-only. The extract is a `SELECT`. It does not insert, and it does not take the advisory lock the seal takes.

Nothing under `src/lms` on the smoke branch inserts into `lms.audit_event`. `ENGINE_READ_STEPS` ends with `post_and_audit`. The Python ledger posts journals in memory and does not append this table. Until that write exists, the extract returns the rows that SQL has, which the current Python paths do not produce (RX41). This draft does not add the writer.

The configuration note says the payload must not contain an identity number, a card number, or a credential. The extract returns `payload` as stored. It does not join `frozen_id_number` onto the row.

### 7.2 Filter

Both arguments are required.

| Argument | Rule |
| --- | --- |
| `organisation_id` | One organisation. A missing id, or an id that does not match the tenant session variable `lms.organisation_id`, stops the read. A cross-organisation file is not a supported filter. |
| `from_date`, `to_date` | Inclusive Johannesburg dates. `from_date` after `to_date` stops the read. |

An event is inside the range when `value_date(occurred_at)` is between those dates. That is `occurred_at >= value_instant(from_date)` and `occurred_at < value_instant(to_date + one day)`. `value_date` and `value_instant` are `lms_config.calendar`. The filter uses `occurred_at` because that is the column in the primary key, the partition key, and the index `audit_event_org_time`. The table has no ledger value-date column. `recorded_at` is returned and is not the filter.

Order is `recognition_sequence` ascending. §1 orders same-day events by recognition sequence. `occurred_at` alone is not the chain order.

### 7.3 Row fields

| Column | Role |
| --- | --- |
| `organisation_id` | Tenant. Hash input. |
| `event_id` | Hash input. |
| `occurred_at` | Hash input, through the database cast the seal used. Filter input. |
| `recognition_sequence` | Hash input. Chain order. Assigned by the seal. A null sequence fails verification. |
| `event_type` | Hash input. |
| `amount_cents` | Hash input. Required by the seal when `ref_audit_event_type.category` is `financial`. Absent when the category is `operational`. |
| `balance_code` | Hash input. Nullable. |
| `payload` | Hash input, as `jsonb` text produced inside the database. The extract does not re-serialise it in Python. |
| `previous_hash` | Link to the previous row of this organisation. Null on the first row. |
| `row_hash` | SHA-256 of the canonical bytes. |
| `recorded_at` | Returned. Not a hash input. |
| `agreement_id` | Returned. Opaque. Not a hash input. |
| `enigma_person_id` | Returned. Opaque. Not a hash input. |
| `actor_kind`, `actor_enigma_id`, `mandate_id` | Returned. Not hash inputs. |
| `correlation_id`, `causation_id` | Returned. Not hash inputs. |
| `terms_version_id`, `interpretation_set_id` | Returned. Not hash inputs. |
| `currency` | Returned. The column is `ZAR`. Not a hash input. |
| `idempotency_key` | Returned when present. Not a hash input. The uniqueness side table is `lms.audit_idempotency`. |
| `category` | From `lms.ref_audit_event_type`. Not a hash input. |

Seeded financial types include `INTEREST_ACCRUED`, `INTEREST_SUPPRESSED`, `FEE_ACCRUED`, `FEE_SUPPRESSED`, `PAYMENT_RECEIVED`, `PAYMENT_ALLOCATED`, `PRINCIPAL_ADVANCED`, `SETTLEMENT_APPLIED`, `BALANCE_WRITTEN_OFF`, `POSTING_REVERSED`, `DEPOSIT_RECEIVED`, `DEPOSIT_RELEASED`, and `SETOFF_APPLIED`.

Seeded operational types include `TERMS_PUBLISHED`, `ORGANISATION_SETTINGS_CHANGED`, `BRAND_CHANGED`, `FEATURE_FLAG_CHANGED`, `AGREEMENT_STATUS_CHANGED`, `STATEMENT_ISSUED`, `DEBIT_ORDER_SUBMITTED`, `REFERENCE_DATA_PUBLISHED`, and `SETTLEMENT_QUOTED`.

There is no event type for "extract produced". The extract does not invent one and does not insert a row (RX38).

### 7.4 Hash-chain verification fields

The canonical is the expression in `lms.seal_audit_event` after migration 0003. It is quoted so a verifier can replay it. This draft does not translate it into another language.

```text
concat_ws('|',
  organisation_id::text,
  event_id::text,
  coalesce(encode(previous_hash, 'hex'), ''),
  event_type,
  occurred_at::text,
  coalesce(amount_cents::text, ''),
  coalesce(balance_code, ''),
  recognition_sequence::text,
  payload::text)
```

`row_hash` is `digest` of those bytes as UTF-8, algorithm SHA-256 (`public.digest` in the seal). The first row of an organisation has a null `previous_hash`, and the canonical uses an empty string in that position.

`occurred_at::text` depends on the session `TimeZone` and `DateStyle`. The seal does not store those settings. A verifier that runs in a different session can disagree with a genuine hash. This draft does not change the seal and does not add a second canonical. Verification is specified as replaying this expression, and it is not claimed to succeed across session settings (RX37).

The migration 0001 seal omitted `recognition_sequence`. Verification uses the 0003 expression only. A row sealed by the earlier function fails the 0003 expression. There is no seal-version column, so this draft does not try the old expression as a fallback.

For a date window the chain extends outside the window. The trailer carries the predecessor so the first in-range `previous_hash` can be checked.

| Trailer field | Meaning |
| --- | --- |
| `predecessor_event_id` | The row of this organisation with the greatest `recognition_sequence` still below the window. Empty when the window starts at sequence 1. |
| `predecessor_row_hash` | That row's `row_hash`. Must equal the first in-range `previous_hash`. |
| `predecessor_recognition_sequence` | That sequence. The first in-range sequence must be this value plus one, or 1 when there is no predecessor. |
| `window_first_sequence`, `window_last_sequence` | Sequences inside the filter. |
| `links_ok` | Each `previous_hash` equals the previous row's `row_hash`, and the sequences increase by one. |
| `hashes_ok` | Each recomputed digest equals `row_hash`. |
| `chain_head_last_event_id`, `chain_head_last_hash`, `chain_head_last_sequence`, `chain_head_last_occurred_at` | The current `lms.audit_chain_head` row for the organisation. |
| `head_covered` | True when the window includes `last_sequence`. A window that ends earlier leaves the head unchecked. |
| `verified` | True when `links_ok` and `hashes_ok` are true. `head_covered` is reported separately and does not make an earlier window fail. |

`verified` false stops any use of the extract as evidence. The rows are still returned with the trailer, so the broken link can be seen. The extract does not repair a hash.

## 8. Compliance boundaries

### 8.1 Fees and interest stay inside the NCA limits

§8 says fees and interest charged may never exceed NCA limits. The charge happens in Layer 0:

- Interest uses `resolve_charge` against `ref_interest_cap` and the confirmed repo rate, or `Ledger._rate_and_divisor` when the ledger posts.
- Initiation uses the Table B cap and `initiation_principal_ratio` (15 percent of the principal debt) at booking validation.
- The monthly service fee uses `service_fee_cents` and `ref_service_fee_cap` inside `levy_service_fee`. The VAT election on the snapshot selects the exclusive or inclusive basis (§9).
- Default administration and collection costs call `require_reference_for_posting` and fail while `ref_tariff_amount` has no row (§18).

The extract reports `ex_vat_cents`, `vat_cents`, and the bucket balance. It does not call those functions to recompute or reduce a posted cent. §7 leaves the in-duplum clip off, so a posted charge during an open episode can sit above `Episode.ceiling_cents`. The extract shows the posted cent and the ceiling. It does not clip the file.

### 8.2 NCR number on NCA communications

The task's boundary matches the Enigma port gate, once RX24's vocabulary is locked:

- Required on NCA communications and on these extracts for micro and unsecured personal.
- Not required for pure hosting.
- Not required for Lay-by / BNPL.

`ncr_number_required` is the function that already encodes that split. This draft calls it only when `product_code` and `pure_hosting` are stored facts. Until then the call is not made, and an extract that would need the number stops with `ncr-number-unset` (RX22, RX23, RX24, RX25).

A blank number, once the gate returns true, refuses the extract. It does not refuse booking. That sentence is the port decision. It is not a locked rule. This draft follows it for extracts because the task states the same boundary, and it records the conflict with the configuration note's "read it from Enigma" reading.

Statements, section 129 notices, and other NCA communications are outside this draft. The servicing flow already says a statement prints the NCR number and the legal name. This draft does not redesign that document. The same unset number blocks that print, for the same reason.

`cfg_brand` does not supply the number. A brand footer is not a substitute.

### 8.3 Frozen identity is what the extracts print

§16 freezes name, ID number, and service address at booking. SACRRA fields 2, 3, 9, 11, and 14–17, and any Form 39 consumer attribute that is one of those three, use `LoanAccount.frozen_full_name`, `frozen_id_number`, and `frozen_service_address`.

The extract does not call `EnigmaStub.check`, `LiveIdentity`, or `communication_preferences` to refresh those three. Email, mobile, and preferred channel are live Enigma facts in the port sketch. They are not copied onto the agreement, and they are not copied onto these extracts (RX14).

The frozen name is not split into surname and forenames. The frozen address is not split into four lines and a postal code. The frozen ID number is not classified as a SA ID and is not decoded into gender or date of birth (RX11, RX12, RX13).

## 9. Sequence of calls

The sequence is a read. Mandate is first because §15 fails closed when authority is unclear. The action name is not in the port's action list. The sequence stops there until RX40 is locked. The ledger and configuration calls below are the calls that run once an action exists and `lookup_mandate` has returned a clear allow. They are not reached by inventing the action string.

### 9.1 SACRRA monthly snapshot

1. `lookup_mandate` for the extract action, the organisation, and the product. Stop while RX40 is open.
2. Read `pure_hosting` and the Enigma product code from their stored columns. Stop while RX23 or RX24 is open. When both exist, call `ncr_number_required`. When it returns true, read the NCR number from the store RX22 eventually names. A blank value stops the file. When it returns false, the file does not carry the number.
3. `organisation_context` for `legal_name`. Stop on timeout, an ambiguous status, or a suspended or closed organisation (§15).
4. `LedgerStore.accounts_for(organisation_id)`. Keep `instrument_kind == "loan"`.
5. For each parent, read `LedgerStore.transactions_for`. If any transaction has `value_date <= D` and `value_date(recognised_at) > D`, stop with `balance-restated` (RX10).
6. `Ledger.bucket_balance` for each debit-normal bucket and for `laybye_hold`, `as_of=D`.
7. Read `snapshot`, the frozen identity, `disbursement_value_date`, `cash_advanced_cents`, the current `ScheduleVersion`, and any open `Episode` from the account. Do not call `resolve_customer_settings`.
8. Assemble the internal fact set in section 5.4 from those reads. The fact set is the posted position. While RX9 is open it is not labelled as a complete end-of-day snapshot, and the extract does not post the missing accrual.
9. Leave every L700 column whose Emit cell is unset empty. While RX3 is open, the mandatory set is unknown, so no L700 file is emitted. The internal fact set and the empty prescribed columns are the readiness output.

`Ledger.statement` and `Servicing.issue_statement` are not in this sequence.

### 9.2 Form 39

1. The same mandate stop as 9.1.
2. The same NCR-number stop as 9.1 when the period contains a product for which the gate returns true. A period that cannot be classified because RX24 is open stops.
3. `organisation_context` for the registered name.
4. `LedgerStore.accounts_for`. Parents with `disbursement_value_date` inside the period are the candidate "entered into" set. The rand value stays unset while RX34 is open.
5. The restatement check from 9.1 step 5, using the period-end date as `D`.
6. `bucket_balance` at the period end for the gross-book candidate, grouped by `snapshot.classification`.
7. `cfg_product_terms` and `cfg_fee_rule` for the annual pricing block, and the posted charges for the levied amounts. Both are listed. Neither is chosen as the form answer while RX35 is open.
8. Application, demographic, provision, write-off, and age-analysis elements stay unset (RX28–RX33). The form is a readiness extract: populated cells are the ones with a source, and the gap list travels with the file. It is not a submission.

### 9.3 Audit extract

1. The same mandate stop as 9.1. The audit extract is still an organisation read.
2. `value_instant(from_date)` and `value_instant(to_date + one day)` from `lms_config.calendar`.
3. `SELECT` from `lms.audit_event` for that `organisation_id` and that instant range, ordered by `recognition_sequence`. Join `lms.ref_audit_event_type` for `category`.
4. `SELECT` the predecessor row: same organisation, greatest `recognition_sequence` strictly below the first row in the window.
5. `SELECT` `lms.audit_chain_head` for the organisation.
6. Replay the section 7.4 expression inside the database for each in-range row. Compare `previous_hash`, the sequence step, and `row_hash`. Fill the trailer.
7. Return the rows and the trailer. Do not insert.

No ledger balance call is required for the audit extract. The financial amount on the row is `amount_cents`, which the seal required for a financial type. It is not recomputed from `ledger_entry`.

## 10. Day-1 classifications and these files

| Classification | Ledger `book` | SACRRA row | Form 39 credit-type line | NCR number gate |
| --- | --- | --- | --- | --- |
| `short_term` | Accepted | One parent row. Account-type code unset (RX5). | Candidate for the short-term line, once RX26 accepts that placement. | Waits on RX24. The task's "micro" is this conflict. |
| `unsecured` | Accepted | One parent row. Account-type code unset. | Candidate for the unsecured line, once RX26 accepts that placement. | Waits on RX24. |
| `zero_cost` | Accepted. A positive charge is rejected. | A row only if a later lock says a zero-cost plan is credit information under regulation 19(13). | Not placed on an NCA line by this draft. | The port's BNPL code is exempt. The ledger code is not that port code (RX24). |
| `cpa_layby` | Accepted as a CPA section 62 lay-by. | Same as `zero_cost`. | Not placed on an NCA line. | Same conflict. |
| Linked lay-by hold | Child of a `short_term` parent (§4) | Included in the parent. No second row. | Included in the parent. The hold is not a second agreement and is not subtracted from principal. | Follows the parent. |
| `mortgage`, `credit_facility`, developmental, `incidental` | `book` rejects them, except `incidental`, which `validate_terms` allows and the current `Ledger.book` does not | No row | Form line unset, not zero (RX36) | Not a Day-1 extract |

## 11. Gaps

Each gap needs either a locked decision or a stored fact. This draft does not close any of them.

| Id | Gap | What is blocked |
| --- | --- | --- |
| RX1 | SACRRA allows month-end or an agreed billing date. §12 does not lock the statement period. | The scheduled as-of date. The caller must pass `D`. |
| RX2 | Submission timelines are "agreed timelines" in the overview. No calendar is transcribed. | The day the file is due. |
| RX3 | Daily 58-field layout, header, footer, record-type character, and the 930 validation rules are not in the repo. Field 7's 25-character account number has no truncation rule. | Emitting a file the bureaus will load. |
| RX4 | SACRRA status codes are not locked. `Episode` and `AgreementRecord.status` are different facts. | Fields 38 and 41. |
| RX5 | Account-type codes `M`, `P`, and `I` are named in the guideline. Code `L` disagrees across the copies fetched. No map from `classification`. | Field 28. |
| RX6 | Months in arrears is an ageing count. §6 has one default test. No month count is locked. | Field 37. A zero is not a substitute. |
| RX7 | Amount overdue is not defined on top of "remaining cents already due". | Field 35. |
| RX8 | §4 keeps principal gross and keeps the hold off that figure. The L700 definition of current balance was not on the pages read. | Field 33. The section 4 sum is available. It is not written into the L700 column until this is confirmed. |
| RX9 | No marker that accrual for `D` has been posted. §8 allows capitalisation on another day. | Knowing the snapshot is up to date. The extract does not post. |
| RX10 | A later reversal carries the original value date and changes `bucket_balance` for an earlier `D`. No submitted-file store exists. | Re-extracting a month. The extract stops with `balance-restated`. |
| RX11 | `frozen_full_name` is one string. | Surname and forenames. |
| RX12 | `frozen_id_number` is one string. Kind, gender, and date of birth are not stored and are not derived. | Fields 2–5, and Form 39 gender. |
| RX13 | `frozen_service_address` is one string. Postal address is not a frozen field. | Address lines and postal codes. |
| RX14 | Telephone, employer, income, and occupation are not stored. Live contact details are not frozen. | Fields 46–52. |
| RX15 | Branch code and the SACRRA supplier reference are not stored. | Fields 6 and 42–45, and the file header. |
| RX16 | One `person_id`. Sub-account and joint-participant counts are not defined. | Fields 8 and 55. |
| RX17 | No sale-to-third-party command or column. | Fields 53 and 54. |
| RX18 | The contractual instalment is not one column. Schedule lines are principal slices. | Fields 36 and 40. |
| RX19 | `payment_frequency` tokens are locked. L700 payment-type and frequency codes are not. | Fields 27 and 39. |
| RX20 | The overview gives N 8 for dates and does not, on the pages read, state the digit order. | Every date column. |
| RX21 | Opening balance versus credit limit, and cash advanced versus principal debt. | Field 32. |
| RX22 | NCR number: configuration and servicing say Enigma, copied to the pin; the Enigma port says LMS tenant attribute; §15 lists neither store. | Every NCA extract and communication that the gate says needs the number. |
| RX23 | `pure_hosting` is not a column. Unset is not false and not true. | Calling `ncr_number_required`. |
| RX24 | Port product codes and ledger classifications are two vocabularies. `loan_account` does not store `enigma_enrolment_code`. | The gate, and the words "micro" and "Lay-by / BNPL" in the task. |
| RX25 | No current interface returns an NCR number. The pin column is a dataclass. The stub does not include it. | Satisfying the gate when it returns true. |
| RX26 | The current Form 39 artwork was not transcribed. Gazette 28531 is a February 2006 draft, and the OCR mixes in other forms. | Filing Form 39. |
| RX27 | The R15 million disbursement test, and "per fee category", are not stored. | Quarterly versus annual submission. |
| RX28 | Applications received and rejected are not ledger rows. | Form 39 section 1.1 and the HDP application lines. |
| RX29 | Province, gender, HDP status, juristic person, and rural or low-density status are not stored. | Form 39 distribution lines. |
| RX30 | Income and the meaning of low income are not stored and not locked. | Form 39 low-income lines. |
| RX31 | No provision balance. The market-report glossary is not yet a lock for the form. | Net debtors book. Gross is the section 4 sum only. |
| RX32 | `BALANCE_WRITTEN_OFF` is seeded. `Ledger` has no write-off method. | Write-off rand value and count. |
| RX33 | Draft age-analysis buckets have no locked day-count. | The age-analysis block. |
| RX34 | "Entered into" is not locked as disbursement date or as cash advanced. | Form 39 section 1.2. |
| RX35 | Annual pricing bands are OCR-damaged. "Fee that will be charged" is not locked as tariff or as levied cents. | The annual pricing section. |
| RX36 | Mortgage, facility, secured, and developmental lines cannot be booked on Day-1. `zero_cost` and `cpa_layby` are not placed on an NCA line. A zero is not written for an absent type. | Those form lines. |
| RX37 | The hash casts `occurred_at::text`. Session `TimeZone` and `DateStyle` are not on the row. The 0001 canonical is not a fallback. | Claiming `hashes_ok` across sessions. |
| RX38 | No audit event type for an extract run. | Recording that the extract was produced. The read still does not insert. |
| RX39 | Ledger `organisation_id` is `text`. Configuration and `audit_event` use `uuid`. | A join across those tables. |
| RX40 | The Enigma port's action list has `lms.export.borrower_data` and no regulatory-extract action. | The first call of every sequence. |
| RX41 | `src/lms` does not insert `lms.audit_event`. `post_and_audit` is a named step without a Python writer. | Rows in the audit extract. Closure dates that would have been operational events. |
| RX43 | The smoke branch's locked file is behind `main`. | Anyone reading the branch copy as the rule. This draft follows `main`. |
| RX50 | L700 amounts are N 9. The overview does not say whether the two cents are implied. Ledger amounts are cents. | Scaling fields 32, 33, 35, and 36. |

RX8 is recorded even though section 4 already states the gross-principal sum. The sum is the locked balance. Confirming that SACRRA's "current balance" is that sum is the open point.

## 12. What this draft does not change

No production code, no migration, and no seed change. The locked file is unchanged. `ncr_number_required` is called as it stands and is not edited. The seal's canonical is not edited. Caps, allocation, and the in-duplum clip stay in Layer 0.
