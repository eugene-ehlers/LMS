# Regulatory extracts — implementation note

Layer 1. Design: `docs/regulatory/layer1-draft.md`. Locks: `docs/LOCKED_DECISIONS.md` on `main` (28 October 2026).

This layer reads. It does not book, accrue, allocate, issue a statement, run a lay-by claim, or run collections.

## Stable signatures

```text
ncr_number_required(*, classification: str, pure_hosting: bool) -> bool

read_ncr_number(compliance: ComplianceStore, organisation_id: str) -> str | None

require_ncr_for_extract(
    compliance,
    *,
    organisation_id: str,
    classifications: tuple[str, ...],
    pure_hosting: bool | None,
) -> str | None

build_sacrra_extract(
    ledger: Ledger,
    compliance: ComplianceStore,
    *,
    organisation_id: str,
    as_of: date,
    pure_hosting: bool | None,
) -> SacrraExtract

build_form39_readiness(
    ledger: Ledger,
    compliance: ComplianceStore,
    *,
    organisation_id: str,
    period_start: date,
    period_end: date,
    pure_hosting: bool | None,
) -> Form39Readiness

AuditLog.append(
    *,
    organisation_id: str,
    occurred_at: datetime,
    event_type: str,
    category: str,
    amount_cents: int | None = None,
    balance_code: str | None = None,
    payload: Mapping | None = None,
    agreement_id: str | None = None,
    enigma_person_id: str | None = None,
) -> AuditRecord

AuditLog.extract(
    *,
    organisation_id: str,
    from_date: date,
    to_date: date,
) -> AuditExtract
```

`SacrraExtract.file_bytes` is always `None`. `SacrraRow.status_code`, `months_in_arrears`, and `account_type_code` are always `None`. `Form39Readiness.not_stored` is the fixed list of elements that have no column.

`require_ncr_for_extract` raises `RegulatoryError` with code `ncr-number-unset` or `pure-hosting-unset`.

## Calls into the ledger and configuration

| Step | Call | Lock |
| --- | --- | --- |
| NCR number and legal name | `ComplianceStore.find` (`lms_config.compliance`). Enigma is not called. | §15, §21 |
| Gate | `ncr_number_required` | §21 |
| Parent loans | `LedgerStore.accounts_for`. Children with `instrument_kind == "laybye_hold"` are not rows. | §4 |
| Balances | `Ledger.bucket_balance(account, bucket, as_of=date)` | §1 |
| Hold | `bucket_balance` on the child for `laybye_hold`. Not subtracted from `principal`. | §4 |
| Identity | `LoanAccount.frozen_full_name`, `frozen_id_number`, `frozen_service_address` | §16 |
| Classification | `LoanAccount.snapshot.classification`, copied at booking | §19 |
| Unbilled interest | No memo is added. `accrue_day` posts no bucket entry. `bill_interest` does. | §6 |
| Caps and clip | Not called. Posted cents are the reported cents. `IN_DUPLUM_CLIP_POSTS` stays false. | §7, §8, §9 |
| Audit dates | `lms_config.calendar.value_date` | §1 |
| Audit chain | `AuditLog` assigns `recognition_sequence`, `previous_hash`, and `row_hash` | §1 |

`ComplianceStore.find` was added so a missing row is not an error. `require` is unchanged and still fails closed for statements.

## Gaps

Raised, not given a default.

| Id | Gap |
| --- | --- |
| RX3 | L700 mandatory rules are not locked. No file is emitted. |
| RX4, RX5, RX6 | Status code, account type, and months in arrears stay `None`. §6 does not define them. |
| RX9 | Nothing records that the as-of day's accrual has been posted. The extract does not post it. |
| RX10 | §1 stamps a reversal with the original value date. A later reversal changes `bucket_balance` for that date. No submitted-file table exists. |
| RX11–RX13 | Frozen name, ID number, and address stay one string each (§16). |
| RX23 | `pure_hosting` is not a column. The caller passes it. `None` fails closed when a micro or unsecured loan is in the extract. |
| RX24 | §21 says "micro" and "unsecured personal". The ledger classifications are `short_term` and `unsecured`. The Day-1 templates are `micro_short_term` and `unsecured_personal`. This layer uses that reading. |
| RX26, RX27, RX34 | Form 39 artwork, the R15 million test, and the meaning of "entered into" are not locked. Sourced ledger facts are named as ledger facts. |
| RX37 | The Python hash uses ISO timestamps and sorted JSON. `lms.seal_audit_event` uses PostgreSQL `::text`. This verifier checks rows it sealed. |
| RX39 | Ledger organisation ids are text. The SQL compliance primary key is uuid. |
| RX41 | No Python path inserts `lms.audit_event`. The in-process hook is `Servicing.audit` (`AuditLog.append` on book, the pre-disbursement deposit, grant, payment, statement issue, and an in-duplum open or close). `AuditLog.extract` reads those rows. A database caller inserts `lms.audit_event`; `lms.seal_audit_event` hashes the row. Direct `Ledger` posts are not sealed unless the caller appends. |
| RX52 | The compliance row and its SQL check reject a blank NCR number for every organisation. §21 allows a blank number for pure hosting and Laybye/BNPL. Those extracts proceed when the row is absent. |
| RX53 | A linked lay-by parent is `short_term` (§4) and requires an NCR number. `zero_cost` and `cpa_layby` do not. §21 does not say the linked parent is the exempt "Laybye". |
| RX54 | `OrganisationSettings` and `ProductTerms` store `in_duplum_trigger` and `residual_write_off_threshold_cents`. `resolve_customer_settings` copies them. An unset trigger stays `None` at booking so a Layer 0 book that does not choose one still posts. `resolve_in_duplum_trigger` and `Collections.bind` fail closed when they are asked to use it. A null residual resolves to 5 000 cents (Decision 8). Whether booking itself must reject a missing trigger is not settled: Decision 19 says unset elections fail closed, and failing the book would change Layer 0. |
| RX55 | §6 now separates contractual breach from collections default. The ledger on this branch still has one morning check. The extract does not call it and does not report a status. |

## Tests

`python3 -m pytest tests/test_regulatory.py tests/test_statements.py` — 19 passed.

The regulatory tests pin:

- Frozen name, ID number, and service address on the SACRRA row.
- Principal at the caller-supplied value date, before and after a later receipt.
- Unbilled interest at 0 cents, then the billed bucket after `bill_interest`.
- One parent row, hold of 40 000 cents, principal still 100 000 cents.
- NCR number `NCRCP12345` from `ComplianceStore` on both extracts.
- `ncr-number-unset` for a micro loan and for an unsecured loan when the compliance row is missing.
- No NCR number required for `zero_cost` or for `pure_hosting=True`.
- Form 39 sourced gross and cash advanced, and the seven missing elements left without attributes.
- Audit `previous_hash`, `row_hash`, `recognition_sequence`, a predecessor outside the window, and `verified` false after a tampered hash.

`python3 -m pytest tests -k 'not storage_sql'` — 136 passed, 2 failed, 1 skipped. The two failures are `test_layer0_smoke.py` on this base: same-day capitalisation versus recognition sequence, and a rejected statement that still billed interest. This change does not edit that path. The SQL audit test is skipped because `psql` is not installed.
