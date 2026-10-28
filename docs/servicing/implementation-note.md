# Servicing implementation note

Orchestration is `src/lms/servicing/`. It calls the calculation engine (`src/lms/calc/`, PR #8), the configuration layer (`src/lms_config/`, PR #4), and the ledger (`src/lms/ledger/`, PR #9). It does not re-implement their formulas or journals. `docs/LOCKED_DECISIONS.md` (28 October 2026) is the source of truth.

The Enigma client is a stub (`EnigmaStub`). It returns a clear active identity, or timeout, ambiguous, or suspended. There is no session middleware.

## Stable API and state machine

| Method and path | Result |
| --- | --- |
| `POST /v1/agreements` | Resolves elections, checks Enigma, calls the engine, freezes the snapshot and the identity, status `pending_disbursement`. Requires `Idempotency-Key`. |
| `POST /v1/agreements/{id}/disbursements` | Calls `Ledger.book` with the frozen snapshot and the frozen identity. Status `active`. A second call returns the same loan. |
| `POST /v1/payments` | Matched receipts are allocated by `Ledger.post_payment`. Unknown agreements stay `unapplied` and are not posted to a loan. Requires `Idempotency-Key`. |
| `POST /v1/payments/{id}/applications` | Allocates an unapplied receipt. The value date stays the original recognition date (§1). |
| `POST /v1/payments/{id}/reversals` | `Ledger.reverse`. The reversal's value date is the payment's original value date (§1). |
| `POST /v1/organisations/{organisation_id}/clients/{person_id}/statements` | Accrues and bills through the ledger, then `Ledger.issue_statement`. One document per person per organisation (§12). PDF bytes are a stub of the stored figures. |

Agreement status moves `pending_disbursement` → `active` → `in_arrears` ↔ `active` → `settled`. `in_arrears` follows `Ledger.flag_default` (§6, §7). A cure is the same check returning not-in-default. `settled` is set when the ledger principal and the remaining slices and charges are all zero. The morning check does not run on a settled or pending agreement.

Value dates are `lms_config.calendar.value_date`: the Johannesburg calendar date of the recognition timestamp, treated as 00:00 (§1). A naive timestamp is rejected.

Unset elections fail closed through `resolve_customer_settings` (§19). Enigma timeout returns 503 and stores nothing. Ambiguous or suspended enrolment returns 422 and stores nothing (§15). An engine `RuleError` or a ledger `LedgerError` fails the call and does not invent a substitute amount.

## Calls

Booking and disbursement:

1. `EnigmaStub.check` for `agreement.book` or `disbursement.confirm` (§15, §16).
2. `lms_config.validate.validate_terms` and `lms_config.locked.resolve_customer_settings` (§19).
3. Calculation engine, for a short-term or unsecured product: `initiation_cap_ex_vat_cents`, `Agreement` (which applies the 5% / 3% cap and the calendar-year test, §13), `nominal_annual_rate` with `periods_per_year` (§17), and `run` for the advance date with a `Policy` built from the frozen resolution. The amounts inside that `run` are not posted.
4. Disbursement only: `Ledger.book`, passing the organisation settings and product captured at booking. A later settings object is not read (§16, and the configuration rule that a resolved value is copied onto the agreement).

Payments: `Ledger.post_payment`, which calls `allocate_payment` (§8). Reversals: `Ledger.reverse` (§1). Statements: `Ledger.accrue_day`, `Ledger.bill_interest`, `Ledger.levy_service_fee` (which calls `opening_service_fraction` and `service_fee_cents`, §5 and §9), then `Ledger.issue_statement` (§12). Default: `Ledger.flag_default`, which calls `is_in_default_at_morning_check`. The threshold instalment is the original principal slice plus levied charges that share that due date. Unbilled interest is not a charge, so it is not included (§6).

`Ledger.clip_in_duplum` is not called. It raises `in-duplum-clip-off` (§7).

## Gaps raised, not solved

- §6 says leniency is per customer. `resolve_customer_settings` documents "customer" as the credit-provider organisation, with a product override. Servicing calls that function. It does not add a per-person leniency store.
- The ledger has no unallocated-suspense account. An unmatched receipt is held by servicing until `applications` posts it. It is not a second ledger.
- The engine has no `validate_booking` symbol. The calls above are the stable surface. `run` may still apply a Nedbank clip inside its pure state. The engine note says that clip stays on. §7 says the clip stays off, and the ledger refuses to post one. Servicing does not copy `run`'s balances onto the ledger. The conflict is not resolved here.
- `run` computes its own initiation fee. The ledger posts the caller-supplied amount, after `initiation_cap_ex_vat_cents` says it is within the cap. Those two amounts are not forced to be equal. A zero fee is accepted (§3).
- Configuration stores repo-fall option A as `contract_rate`. The engine stores it as `contract_rate_continues`. Servicing uses the ledger's existing mapper. It does not add a third token.
- §9 does not store a VAT rate. A service-fee levy fails closed until the statement caller supplies `vat_rate`. 15% is not assumed.
- Servicing does not open the configuration SQL reads (`ENGINE_READ_STEPS`). `interest_cap_present` is a required boolean on the statement call. It is not defaulted to true.
- `periods_per_year` follows the engine: 12 for short-term, 1 for unsecured. §17 does not say whether a weekly instalment frequency means 52 or 365/7. That question is not answered here.
- §1 does not say which date wins when the system recognises a concluded loan on a later calendar day. Servicing passes the recognition timestamp through `value_date`, which uses the Johannesburg date of that instant and does not backdate.
- §13's small residual write-off, restructuring, and the section 104 notice are not implemented. §4 death, funeral, and section 124 application are not routes. §17's affordability ceiling has no field, so rounding is not compared with one.
- §8 does not place the further monthly fee among the named fee buckets. The ledger fails closed when a short payment would have to choose. Servicing propagates that error.
- `Ledger.book` mints its own loan id at disbursement. The servicing agreement id and the ledger loan id are different. The frozen name is still the name captured at booking.

## Tests

`PYTHONPATH=src python3 -m pytest tests -q` on 28 October 2026 at 09:24 SAST: 114 passed, 2 skipped. The skips are the Postgres ledger checks, because Postgres was not running. `tests/test_servicing.py` is 12 passed, covering booking and disbursement, matched allocation, suspense until apply, reversal on the original value date, fail-closed on a missing repo-fall election, snapshot isolation after a later policy, and the state machine through arrears, cure, and settlement.
