# Regulatory extracts — Layer 1 draft

**Status: Layer 1 draft, with an implementation in `src/lms/regulatory`. This file is not a locked decision.**

The field catalogue and the open mandatory-field rules are in `docs/regulatory/extract-layouts.md`.

`docs/LOCKED_DECISIONS.md` on `main` (last updated 2026-10-28, including decisions 20 and 21) is the source of truth. The implementation calls the ledger, `lms_config.compliance`, and `lms.audit_event` through `read_lms_audit_event`. It does not re-implement interest, allocation, caps, the audit seal, statements, lay-by claims, or collections.

The code sits on the Layer 0 ledger and the LMS compliance store. `main` itself has no Python interfaces.

## 1. Behaviour and the lock it follows

| Behaviour | Lock |
| --- | --- |
| An as-of date and a filter date are Johannesburg calendar dates. A caller supplies the date. The extract does not choose month-end or a billing date. | §1 |
| Balances are `Ledger.bucket_balance` for transactions with `value_date` on or before that date. | §1 |
| Same-day order is the recognition sequence the ledger already stored. The extract does not post accrual or receipts. | §1 |
| A reversal keeps the original value date, so a later reversal changes an earlier `bucket_balance`. There is no stored submitted file. The extract returns the ledger sum. | §1. Gap RX10. |
| Day-1 short-term and unsecured keep initiation non-capitalised. The balance includes `capitalised_initiation_cents` only when the ledger posted it. | §2 |
| A zero rate or a zero fee still produces a row. | §3 |
| A linked lay-by is one parent row. The hold is the child bucket. Principal stays gross. The hold is not subtracted. | §4 |
| The extract does not accrue, so it does not choose a day count. | §5 |
| Unbilled interest is the `interest_accrual` memo. It stays out of the balance until `bill_interest` debits it. | §6 |
| Contractual breach and collections default are two concepts. Neither is converted into a SACRRA status or a month count. | §6. Codes stay unset. |
| The in-duplum clip stays off. Reported interest and fees are the posted cents. | §7 |
| Posted fees and interest are not passed through a second NCA cap. | §8 |
| A full write-off journal can be posted. The Form 39 write-off cell stays empty. No count or rand total is invented from that journal. | §8. Gap recorded with the locked file. |
| The service-fee cap was applied when `levy_service_fee` ran. The extract reads the posted cents. | §9 |
| SACRRA grain is the agreement. The statement grain stays one document per client. | §12 |
| The contractual instalment is not one stored column. It is not guessed. | §13 |
| `payment_frequency` is the locked token. The L700 numeric code is not mapped. | §14 |
| Enigma is identity and access. The extract does not call it for the NCR number, the legal name, or the frozen consumer fields. | §15 |
| Consumer name, ID number, and service address are the values frozen on the loan at booking. | §16 |
| Posted cents are already half-up. The extract does not round again. | §17 |
| A missing tariff fails the levy in the ledger. The extract does not look up a tariff to change a posted charge. | §18 |
| `pure_hosting` is not one of the stored elections. `None` fails closed when a micro or unsecured loan is in the extract. It is not read as false. | §19 style for an unset fact. The column is gap RX23. §19 does not list this flag. |
| The NCR number is read from `ComplianceStore` / `lms.cfg_provider_compliance`. | §15, §21 |
| It is required for `short_term` (Day-1 template `micro_short_term`) and `unsecured` (template `unsecured_personal`), unless `pure_hosting` is true. | §21. The classification strings are gap RX24. |
| It is not required for `zero_cost` (template `bnpl_zero`) or `cpa_layby` (template `layby_goods`). | §21. Gap RX24 and RX53. |
| A blank or missing number blocks those micro and unsecured extracts. The extract does not book, so booking stays open. | §21 |
| A linked lay-by parent remains `short_term` and still requires the number. The child is not its own row. | §4, §21. Gap RX53. |
| Audit rows are ordered by `recognition_sequence`. The date filter uses `value_date(occurred_at)`. | §1 |
| One organisation per extract. | §15 |

## 2. SACRRA

Regulation 19(13) and the SACRRA overview of the L700v2 monthly layout are the field list. The overview's 930 validation rules, the daily 58-field layout, the header, and the footer are not in this repository (gap RX3). No file is emitted. `SacrraExtract.file_bytes` is `None`.

`build_sacrra_extract(ledger, compliance, *, organisation_id, as_of, pure_hosting)` returns one `SacrraRow` per parent loan with `disbursement_value_date <= as_of`.

The 56 layout columns are `L700_MONTHLY_FIELDS`. Every `value` is `None`. Sourced facts sit beside the layout and are not copied into a column whose split, code, or scale is unlocked.

| Fact beside the layout | Source | What the row carries |
| --- | --- | --- |
| Name, ID number, service address | Frozen at booking (§16) | The three strings. L700 surname, forename, ID, gender, date of birth, and address columns stay empty. |
| Loan id | `LoanAccount.loan_id` | The id. The A 25 account-number column stays empty. Truncation is not locked. |
| Date account opened | `disbursement_value_date` (§1) | The date on the row. The N 8 column stays empty (gap RX20). |
| Posted buckets | `Ledger.bucket_balance` at `as_of` (§1, §4, §6) | `bucket_cents`. The N 9 amount columns stay empty (gap RX50). `amount_scale` is `None`. |
| Lay-by hold | Child `laybye_hold` at `as_of` (§4) | `laybye_hold_cents`. Not subtracted from principal. Not its own row. |
| Status code, months in arrears, account type | No locked code list (§6) | `None` on the row and in fields 37, 38, and 28. |
| NCR number | `ComplianceStore` (§21) | On the extract when the gate requires it, or when a row happens to be stored. Not an L700 body column. |

Phones, employer, income, occupation, branch code, supplier reference, and third-party sale fields are not stored. They are not filled.

## 3. Form 39 readiness

Regulation 64, as published in the NCR compliance text:

- Annual disbursements above R15 million, or per fee category: quarterly. Quarter 1 is due 15 May, quarter 2 on 15 August, quarter 3 on 15 November, quarter 4 on 15 February.
- Every other credit provider: 15 February for 1 January–31 December.

The R15 million test is not stored. The caller supplies `period_start` and `period_end` (gap RX27). The current Schedule 1 artwork was not transcribed (gap RX26).

`build_form39_readiness` returns these sourced facts:

| Fact | Call |
| --- | --- |
| NCR number | `ComplianceStore.find` (§21). Missing stays `None` when the gate does not require it. |
| Legal name | The same compliance row, when a row exists (§15). |
| Gross owed cents, and the same total by `snapshot.classification` | `Ledger.bucket_balance` at `period_end` for the eight debit-normal buckets (§1, §8). |
| Lay-by hold | Child bucket at `period_end` (§4). Not subtracted. |
| Agreements disbursed in the period, and their `cash_advanced_cents` | Parents whose `disbursement_value_date` falls in the period. This is the stored advance, not a ruling on which Form 39 cell it fills (gap RX34). |

`not_stored` is exactly: applications, province, gender, income, provisions, write-offs, age analysis. Each of those attributes is present and `None`. No zero is written for them. `filing_rule` quotes regulation 64 and is not used to choose the period.

## 4. Audit extract

`read_lms_audit_event(execute, organisation_id, from_date, to_date)` reads `lms.audit_event` for one organisation. The range is inclusive on the Johannesburg day of `occurred_at`: `occurred_at >= value_instant(from_date)` and `occurred_at < value_instant(to_date + one day)`. Order is `recognition_sequence`. The query joins `lms.ref_audit_event_type` for the category and compares `row_hash` with `public.digest` of the migration 0003 canonical. The Python code does not hash those rows.

The trailer carries the predecessor (`predecessor_event_id`, `predecessor_row_hash`, `predecessor_recognition_sequence`) and `lms.audit_chain_head` (`chain_head_last_event_id`, `chain_head_last_occurred_at`, `chain_head_last_hash`, `chain_head_last_sequence`), plus `links_ok`, `hashes_ok`, `verified`, and `head_covered`.

`AuditLog` is the in-process hook `Servicing.audit` writes, because no Python path inserts `lms.audit_event` (gap RX41). `AuditLog.extract` has the same trailer. Its hash is SHA-256 over an ISO timestamp and sorted JSON. That is not PostgreSQL `occurred_at::text` (gap RX37). `AuditLog` checks only rows it sealed.

## 5. Sequence of calls

1. `ComplianceStore.find(organisation_id)` for the NCR number and legal name (§15, §21). Enigma is not called.
2. `require_ncr_for_extract` applies decision 21. A required blank number raises `ncr-number-unset`.
3. `LedgerStore.accounts_for(organisation_id)`. Keep `instrument_kind == "loan"` (§4).
4. `Ledger.bucket_balance(account, bucket, as_of=...)` for each owed bucket, and for each child's `laybye_hold` (§1, §4).
5. Read `frozen_full_name`, `frozen_id_number`, `frozen_service_address`, and `snapshot.classification` from the account (§16). `resolve_customer_settings` is not called again (§19: the snapshot is the booking copy).
6. The audit extract does not call the ledger. `read_lms_audit_event` runs the `lms.audit_event` and `lms.audit_chain_head` queries. `AuditLog.extract` reads the in-process hook. Both use `lms_config.calendar` for the Johannesburg day (§1).

`Ledger.statement`, `clip_in_duplum`, `service_fee_cents`, and `resolve_charge` are not in this sequence (§7, §8, §9).

## 6. Gaps

| Id | Gap |
| --- | --- |
| RX3 | L700 mandatory rules, header, footer, and the daily layout are not locked. No file is emitted. |
| RX4, RX6 | SACRRA status codes and months in arrears are not locked. §6 does not define them. They stay `None`. |
| RX5 | Account-type codes are not locked. `account_type_code` stays `None`. |
| RX9 | No marker that accrual for the as-of date has been posted. The extract reads what is already posted and does not post. |
| RX10 | A later reversal rewrites an earlier value-date balance (§1). No submitted-file store exists. |
| RX11, RX12, RX13 | The frozen name, ID number, and service address are single strings. They are not split or decoded (§16). |
| RX20 | N 8 date digit order is not in the overview pages read. Date columns stay empty. |
| RX50 | L700 amounts are N 9. The overview does not say whether the cents are implied. Amount columns and `amount_scale` stay empty. Ledger cents stay on the row. |
| RX23 | `pure_hosting` is not a column on `cfg_provider_compliance` or `cfg_organisation_settings`. The caller passes it. `None` fails closed when a requiring loan is present. |
| RX24 | Decision 21 says "micro" and "unsecured personal". The ledger says `short_term` and `unsecured`. The templates are named `micro_short_term` and `unsecured_personal`. That is the reading this layer uses. |
| RX26 | Current Form 39 artwork is not transcribed. |
| RX27 | The R15 million test is not stored. |
| RX34 | "Entered into" is not locked as disbursement date or as cash advanced. Both stored facts are returned under those names. |
| RX37 | `AuditLog` hashes are not the SQL `::text` canonical. `read_lms_audit_event` asks the database to run the migration 0003 expression and does not hash in Python. |
| RX39 | Ledger organisation ids are text. `cfg_provider_compliance.organisation_id` is uuid. The in-memory store uses the ledger's text id. |
| RX41 | The Python ledger does not insert `lms.audit_event`. `Servicing.audit` (`AuditLog`) is the in-process hook this layer reads. A database caller inserts `lms.audit_event`. |
| RX52 | `ComplianceStore.put` and the SQL check reject a blank NCR number for every organisation. Decision 21 allows a blank number for pure hosting and Laybye/BNPL. A missing row is how those extracts proceed. A stored blank number is not representable. |
| RX53 | A linked lay-by parent is `short_term` (§4) and requires an NCR number. `cpa_layby` and `zero_cost` do not. Decision 21's word "Laybye" is not defined as the linked parent. |
| RX54 | Closed for the resolver. `resolve_residual_threshold_cents` fills 10 000 cents when both levels are null. The extracts do not write off and do not apply the threshold. |
| RX55 | §6 now has two default concepts. The ledger morning check on this branch is still one test. Status codes stay unset. |
