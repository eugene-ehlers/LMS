# Regulatory extracts — implementation note

Layer 1. Layouts: `docs/regulatory/extract-layouts.md`. Draft: `docs/regulatory/layer1-draft.md`. Locks: `docs/LOCKED_DECISIONS.md`.

This layer reads. It does not book, accrue, allocate, clip, issue a statement, run a lay-by claim, or run collections. Posted cents are reported as posted. `clip_in_duplum` is not called. The in-duplum clip stays off.

Tests that need a consumer identity or an application call `EnigmaDummy` and `DecisionEngineDummy`. The NCR number is not taken from either dummy. It is taken from `ComplianceStore`. A test number of all zeros is a stored compliance value.

## Stable signatures

```text
build_sacrra_extract(ledger, compliance, *, organisation_id, as_of, pure_hosting) -> SacrraExtract
render_l700_file(extract) -> raises RegulatoryError("mandatory-fields-unlocked")

build_form39_readiness(
    ledger, compliance, *, organisation_id, period_start, period_end, pure_hosting
) -> Form39Readiness

read_lms_audit_event(execute, *, organisation_id, from_date, to_date) -> AuditExtract
AuditLog.extract(*, organisation_id, from_date, to_date) -> AuditExtract

require_ncr_for_extract(compliance, *, organisation_id, classifications, pure_hosting) -> str | None
```

`SacrraExtract.layout` is the 56-field monthly catalogue. Every field `value` is `None`. `file_bytes` is `None`. `status_code`, `months_in_arrears`, `account_type_code`, and `amount_scale` are `None`.

`Form39Readiness.gross_book_cents` is the billed book. The seven `not_stored` attributes exist and are `None`.

`read_lms_audit_event` sends `AUDIT_EVENT_SQL`, `AUDIT_PREDECESSOR_SQL`, and `AUDIT_CHAIN_HEAD_SQL`. `execute(sql, params)` returns mappings. The hash comparison is inside the event query.

## Calls

| Step | Call | Lock |
| --- | --- | --- |
| NCR number and legal name | `ComplianceStore.find` | §15, §21 |
| Gate | `ncr_number_required` | §21 |
| Parent loans | `LedgerStore.accounts_for`, then drop lay-by children and loans with no disbursement date | §4 |
| Balances | `Ledger.bucket_balance(..., as_of=date)` | §1, §6 |
| Hold | `bucket_balance` on the child for `laybye_hold` | §4 |
| Identity | `LoanAccount.frozen_full_name`, `frozen_id_number`, `frozen_service_address` | §16 |
| Audit dates | `lms_config.calendar.value_instant` | §1 |
| Audit rows | `SELECT` from `lms.audit_event` ordered by `recognition_sequence` | §1, §23 |
| Chain head | `SELECT` from `lms.audit_chain_head` | §23 |

Enigma is not called by the extract. A booking test may call `EnigmaDummy.identity_for_booking` and then pass the frozen strings into `Ledger.book`. The extract reads the account after that.

## Gaps

Raised in `docs/LOCKED_DECISIONS.md` under "Open gaps (not decisions)" and in the layout note. No default was chosen.

| Id | Gap |
| --- | --- |
| RX3 | Mandatory L700 rules are not locked. No file is emitted. |
| RX4, RX5, RX6, RX50 | Status, account type, months in arrears, and the N 9 scale stay empty. |
| RX11–RX13, RX20 | Frozen strings are not split. N 8 dates are not formatted into the layout. |
| RX23, RX24, RX53 | `pure_hosting` is not a column. "Micro" and "Laybye/BNPL" are not the ledger's classification strings. |
| RX27 | The R15 million test is not stored. |
| RX37 | `AuditLog` hashes are not the SQL `::text` canonical. `read_lms_audit_event` does not reimplement that canonical. |
| RX39 | Ledger organisation ids are text. `lms.audit_event.organisation_id` is uuid. The query does not cast one to the other in Python. |
| RX41 | No Python path inserts `lms.audit_event`. `Servicing.audit` remains `AuditLog`. |
| Residual threshold | Decisions 8 and 19 say R100. This branch's `lms_config.locked` still resolves a null threshold to 5 000 cents. The extracts do not write off. |

## Tests

`python3 -m pytest tests/test_regulatory.py`
