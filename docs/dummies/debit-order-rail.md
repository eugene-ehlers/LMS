# Debit-order rail dummy

The LMS submits a collection instruction. The dummy returns a fixed success, a fixed failure, or a fixed unmatched result. It does not call a bank, and it does not build a DebiCheck or other payment file. That file layout is a real-rail concern and is out of scope here.

On a matched success the LMS capitalises due amounts for the recognition date before it allocates the receipt. This dummy does not capitalise or allocate. It returns the receipt the LMS needs in order to do that.

Call sites:

- `rail.submit_collection(instruction)`
- `rail.pull_unmatched_receipts()`

| Scenario | Constructor | `submit_collection` | `pull_unmatched_receipts` |
| --- | --- | --- | --- |
| Fixed success | `DebitOrderRailDummy.fixed_success()` | Matched receipt | Empty |
| Fixed failure | `DebitOrderRailDummy.fixed_failure()` | Failure, no receipt | Empty |
| Fixed unmatched | `DebitOrderRailDummy.fixed_unmatched()` | Unmatched receipt built from the instruction | One canned unmatched receipt, independent of the instruction |

Receipt sequence starts at 1 on each dummy instance and increases only when a receipt is emitted. Two receipts recognised at 00:00 on the same calendar day are ordered by this sequence.

## Request

`CollectionInstruction`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `loan_number` | string | yes | |
| `amount_cents` | int | yes | Zero or positive cents. Echoed unchanged. Not combined with credit life or any other charge |
| `due_date` | calendar date | yes | Kept as a date. A datetime is rejected. Not copied onto the receipt |
| `recognition_at` | calendar date or timezone-aware datetime | yes | Stored as 00:00 Africa/Johannesburg |
| `id_number` | string | no | Copied onto an unmatched receipt when present, for later matching |

Example:

```text
loan_number: LN-1001
amount_cents: 25000
due_date: 2026-11-03
recognition_at: 2026-10-28T15:45:00+02:00
id_number: 0000000000000
```

The stored recognition instant for that example is `2026-10-28T00:00:00+02:00`. An instant at `2026-10-28T22:30:00Z` falls on 29 October in Johannesburg, so the recognition instant is `2026-10-29T00:00:00+02:00`.

## Response: success

`CollectionSuccess`, `kind = success`, with a `MatchedReceipt`.

| Field | Type | Notes |
| --- | --- | --- |
| `receipt.kind` | `matched` | |
| `receipt.receipt_sequence` | int | 1, then 2, and so on |
| `receipt.loan_number` | string | From the instruction |
| `receipt.amount_cents` | int | From the instruction |
| `receipt.recognition_at` | datetime | 00:00 Africa/Johannesburg |

```text
kind: success
receipt.kind: matched
receipt.receipt_sequence: 1
receipt.loan_number: LN-1001
receipt.amount_cents: 25000
receipt.recognition_at: 2026-10-28T00:00:00+02:00
```

## Response: failure

`CollectionFailure`, `kind = failure`. There is no receipt and no amount to allocate.

| Field | Type | Notes |
| --- | --- | --- |
| `loan_number` | string | From the instruction |
| `reason` | string | Always `fixed_failure`. Not a bank reason code |
| `kind` | `failure` | |

```text
kind: failure
loan_number: LN-1001
reason: fixed_failure
```

An invalid instruction, such as a negative amount or a naive datetime, is a contract error in every scenario, including fixed failure.

## Response: unmatched

`CollectionUnmatched`, `kind = unmatched`, with an `UnmatchedReceipt`.

| Field | Type | Notes |
| --- | --- | --- |
| `receipt.kind` | `unmatched` | |
| `receipt.receipt_sequence` | int | Next sequence on this instance |
| `receipt.amount_cents` | int | From the instruction |
| `receipt.recognition_at` | datetime | 00:00 Africa/Johannesburg |
| `receipt.loan_number` | string or absent | From the instruction |
| `receipt.id_number` | string or absent | From the instruction, when it was sent |

At least one of `loan_number` and `id_number` is present. The LMS matches later. This dummy does not match.

`pull_unmatched_receipts` in the unmatched scenario returns one canned receipt on every call:

```text
kind: unmatched
receipt_sequence: next sequence
loan_number: LN-FIXED-UNMATCHED
id_number: 0000000000000
amount_cents: 12345
recognition_at: 2026-01-15T00:00:00+02:00
```

That pull is not the submit result. A test that both submits and pulls receives two receipts.
