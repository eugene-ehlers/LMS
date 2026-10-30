# Regulatory extract layouts

Layer 1 read layer. This note is not a locked decision. The locks are `docs/LOCKED_DECISIONS.md`. The code is `src/lms/regulatory`.

The extracts call `Ledger.bucket_balance`, `LedgerStore.accounts_for`, `ComplianceStore.find`, and `lms.audit_event`. They do not accrue, allocate, clip, or apply a second NCA cap. Posted fees and interest are the cents the ledger already stored. `IN_DUPLUM_CLIP_POSTS` stays false.

Identity is the name, ID number, and service address frozen at booking. A later Enigma read is not copied onto the row. The NCR number is the LMS compliance row. Enigma does not hold it. A test number of all zeros is accepted. A missing or blank number fails closed on an NCA extract.

## SACRRA monthly L700v2

Regulation 19(13) requires credit information in the form the NCR prescribes. The table is the 56-field monthly layout from the SACRRA overview of that guideline. Positions run from 1 to 700. The catalogue in code is `L700_MONTHLY_FIELDS`.

Every layout `value` is empty. `render_l700_file` raises `mandatory-fields-unlocked`. `SacrraExtract.file_bytes` is `None`. No submission file is written.

| No. | Name | Positions | Format | Why the value is empty |
| --- | --- | --- | --- | --- |
| 1 | DATA | 1 | A 1 | Record-type character is not in the overview pages in this repo. |
| 2 | SA ID NUMBER | 2–14 | N 13 | The frozen ID number is one string. It is not classified as a SA ID. |
| 3 | NON-SA ID NUMBER | 15–30 | A 16 | Same string. The kind of identifier is not stored. |
| 4 | GENDER | 31 | A 1 | Not stored. The ID number is not decoded. |
| 5 | DATE OF BIRTH | 32–39 | N 8 | Not stored. The ID number is not decoded. |
| 6 | BRANCH CODE | 40–47 | A 8 | Not stored. |
| 7 | ACCOUNT NO. | 48–72 | A 25 | `loan_id` is on the row. The 25-character rule is not locked, so the column stays empty. |
| 8 | SUB-ACCOUNT NO. | 73–76 | A 4 | A linked lay-by is not a sub-account. |
| 9 | SURNAME | 77–101 | A 25 | `frozen_full_name` is one string. It is not split. |
| 10 | TITLE | 102–106 | A 5 | Not stored. |
| 11 | FORENAME OR INITIAL 1 | 107–120 | A 14 | The frozen name is not split. |
| 12 | FORENAME OR INITIAL 2 | 121–134 | A 14 | Not stored. |
| 13 | FORENAME OR INITIAL 3 | 135–148 | A 14 | Not stored. |
| 14–17 | RESIDENTIAL ADDRESS LINE 1–4 | 149–248 | A 25 each | `frozen_service_address` is one string. It is not split. |
| 18 | POSTAL CODE OF RESIDENTIAL ADDRESS | 249–254 | A 6 | Not stored. |
| 19 | OWNER / TENANT | 255 | A 1 | Not stored. |
| 20–23 | POSTAL ADDRESS LINE 1–4 | 256–355 | A 25 each | No second address is frozen. |
| 24 | POSTAL CODE OF POSTAL ADDRESS | 356–361 | A 6 | Not stored. |
| 25 | OWNERSHIP TYPE | 362–363 | A 2 | Codes are not locked. |
| 26 | LOAN REASON CODE | 364–365 | A 2 | Not stored. |
| 27 | PAYMENT TYPE | 366–367 | A 2 | Codes are not locked. `payment_frequency` is a different fact. |
| 28 | TYPE OF ACCOUNT | 368–369 | A 2 | Account-type codes are not locked. `account_type_code` is `None`. |
| 29 | DATE ACCOUNT OPENED | 370–377 | N 8 | `disbursement_value_date` is on the row. N 8 digit order is not locked. |
| 30 | DEFERRED PAYMENT DATE | 378–385 | N 8 | N 8 digit order is not locked. |
| 31 | DATE OF LAST PAYMENT | 386–393 | N 8 | N 8 digit order is not locked. |
| 32 | OPENING BALANCE / CREDIT LIMIT | 394–402 | N 9 | N 9 scale is not locked. `amount_scale` is `None`. |
| 33 | CURRENT BALANCE | 403–411 | N 9 | Ledger cents are on `bucket_cents`. The N 9 column stays empty. |
| 34 | CURRENT BALANCE INDICATOR | 412 | A 1 | The overview does not give the character. |
| 35 | AMOUNT OVERDUE | 413–421 | N 9 | N 9 scale is not locked. |
| 36 | INSTALMENT AMOUNT | 422–430 | N 9 | The contractual instalment is not one column. N 9 scale is not locked. |
| 37 | MONTHS IN ARREARS | 431–432 | N 2 | Not locked. A zero is not written. `months_in_arrears` is `None`. |
| 38 | STATUS CODE | 433–434 | A 2 | Not locked. `status_code` is `None`. |
| 39 | REPAYMENT FREQUENCY | 435–436 | N 2 | The locked token is not a numeric code. |
| 40 | TERMS | 437–440 | N 4 | Not locked. |
| 41 | STATUS DATE | 441–448 | N 8 | Stays empty with the status code. |
| 42 | OLD SUPPLIER BRANCH CODE | 449–456 | A 8 | Not stored. |
| 43 | OLD ACCOUNT NUMBER | 457–481 | A 25 | Not stored. |
| 44 | OLD SUB-ACCOUNT NUMBER | 482–485 | A 4 | Not stored. |
| 45 | OLD SUPPLIER REFERENCE NUMBER | 486–495 | A 10 | The SACRRA supplier reference is not stored. |
| 46 | HOME TELEPHONE | 496–511 | A 16 | Not frozen at booking. |
| 47 | CELLULAR TELEPHONE | 512–527 | A 16 | Not frozen at booking. |
| 48 | WORK TELEPHONE | 528–543 | A 16 | Not stored. |
| 49 | EMPLOYER DETAIL | 544–603 | A 60 | Not stored. |
| 50 | INCOME | 604–612 | N 9 | Not stored. |
| 51 | INCOME FREQUENCY | 613 | A 1 | Not stored. |
| 52 | OCCUPATION | 614–633 | A 20 | Not stored. |
| 53 | THIRD PARTY NAME | 634–693 | A 60 | Not stored. |
| 54 | ACCOUNT SOLD TO THIRD PARTY | 694–695 | N 2 | Not stored. |
| 55 | NO OF PARTICIPANTS IN JOINT LOAN | 696–698 | N 3 | Not locked. A count of 1 is not written. |
| 56 | FILLER | 699–700 | A 2 | Filler rule is not confirmed. |

Header, footer, the daily 58-field layout, and the overview's validation rules are not in this repository. They are not emitted.

### What a row does carry

`build_sacrra_extract(ledger, compliance, *, organisation_id, as_of, pure_hosting)`:

- One row per parent with `instrument_kind == "loan"` and a `disbursement_value_date` on or before `as_of`. A prepared loan with no disbursement date is omitted. A lay-by child is not a row.
- `frozen_full_name`, `frozen_id_number`, `frozen_service_address`.
- `bucket_cents` from `Ledger.bucket_balance` for `principal`, `interest`, `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, and `additional_monthly`. An `interest_accrual` memo has no entry, so unbilled interest is 0 until `bill_interest`.
- `laybye_hold_cents` from the child bucket. It is not subtracted from `principal_cents`.
- `as_of` is the caller-supplied Johannesburg value date. The extract does not choose month-end or a billing date.

## Form 39

Regulation 64: quarterly when annual disbursements exceed R15 million, otherwise annually by 15 February. The R15 million test is not stored. `build_form39_readiness` does not choose the calendar. The caller supplies `period_start` and `period_end`. `filing_rule` repeats that sentence and is not applied.

Gross book is the sum of the eight debit-normal buckets at `period_end`, parents only. The lay-by hold is reported beside it and is not subtracted. Unbilled interest is excluded until it is billed.

These cells are empty (`None`): applications, province, gender, income, provisions, write-offs, age analysis.

The decision-engine dummy can return an application. That result is not an LMS column, so the applications cell stays empty. A ledger write-off journal clears the billed buckets and is not copied into the write-off cell.

`cash_advanced_cents_disbursed_in_period` is the stored advance for parents disbursed inside the period. It is not a ruling on which form line that figure fills. The current Schedule 1 artwork is not transcribed here.

## Audit extract

`read_lms_audit_event(execute, *, organisation_id, from_date, to_date)`:

- One organisation. A blank id fails closed.
- Inclusive Johannesburg dates on `occurred_at`. `from_date` after `to_date` fails closed.
- `execute` runs `AUDIT_EVENT_SQL`, `AUDIT_PREDECESSOR_SQL`, and `AUDIT_CHAIN_HEAD_SQL`. This process does not open a connection and does not hash.
- The event query filters `lms.audit_event`, joins `lms.ref_audit_event_type`, and orders by `recognition_sequence`.
- `hash_matches` is `row_hash` compared in the database with `public.digest` of the migration 0003 seal expression. The Python canonical is not used for these rows.
- Each row carries `previous_hash`, `row_hash`, and `recognition_sequence`.
- The trailer carries the predecessor link (`predecessor_event_id`, `predecessor_row_hash`, `predecessor_recognition_sequence`) and `audit_chain_head` (`chain_head_last_event_id`, `chain_head_last_occurred_at`, `chain_head_last_hash`, `chain_head_last_sequence`).
- `verified` is true only when the links step by one and every `hash_matches` is true. A broken chain is still returned.

`AuditLog` is the in-process log `Servicing.audit` appends to, because no Python path inserts `lms.audit_event`. `AuditLog.extract` uses the same trailer shape. It verifies rows it sealed with its own canonical. That canonical is not `occurred_at::text`.

## NCR number

`require_ncr_for_extract` reads `ComplianceStore`. It does not call Enigma.

| Classification on the booked snapshot | NCR number |
| --- | --- |
| `short_term` (template `micro_short_term`) | Required, unless the caller passes `pure_hosting=True`. |
| `unsecured` (template `unsecured_personal`) | Required, unless the caller passes `pure_hosting=True`. |
| `zero_cost` (template `bnpl_zero`) | Not required. |
| `cpa_layby` (template `layby_goods`) | Not required. |
| Any other classification | Required. It is not treated as exempt. |

`pure_hosting` is not a column. `None` fails closed when a row would require the number. It is not read as false. The map from decision 21's words "micro" and "Laybye/BNPL" onto these classifications is recorded as an open gap. It is not a locked rule.

A linked lay-by child is not a row. Its parent keeps the parent's classification.

## Open mandatory-field rules

These block an L700 file. They are not given a default.

| Rule | What stays empty |
| --- | --- |
| Mandatory-field set, header, footer, daily layout, validation rules | The file. `render_l700_file` refuses. |
| Status codes | Field 38 and `status_code`. |
| Months in arrears | Field 37 and `months_in_arrears`. A zero is not a substitute. |
| Account-type codes | Field 28 and `account_type_code`. |
| N 9 amount scale | Fields 32, 33, 35, and 36, and `amount_scale`. |
| N 8 digit order | Date columns. |
| How to split a frozen name, ID number, or service address | Fields 2–5, 9, 11, and 14–18. |
| 25-character account number | Field 7. |
| Regulation 64 R15 million test | The filing calendar. The caller supplies the period. |
| Form 39 cells with no column | Applications, province, gender, income, provisions, write-offs, age analysis. |
