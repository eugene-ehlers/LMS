# Batch record schema

Times are ISO 8601 in Africa/Johannesburg with a `+02:00` offset and microsecond precision, for example `2026-10-28T00:15:01.000000+02:00`. The recognition instant is always `T00:00:00.000000+02:00` on the recognition date.

Identifiers are opaque strings. `actor_id` is the person id stored on the audit row. `account_id` is the account identifier.

## Batch run

Stored in `batch_runs`. Returned on the status query as `last_status`, `last_successful_run`, and `last_failed_run`.

| Field | Meaning |
|-------|---------|
| `id` | Run identifier. |
| `organisation_id` | Organisation the run belongs to. |
| `recognition_date` | Calendar date, `YYYY-MM-DD`. |
| `recognition_at` | That date at 00:00 Africa/Johannesburg. |
| `started_at` | When the start was recorded. |
| `finished_at` | When the run finished. Null when the run did not finish. |
| `accounts_processed` | Accounts whose attempt was recorded. |
| `accounts_failed` | How many of those attempts failed. |
| `accounts_at_ceiling` | How many of those accounts had reached the in-duplum ceiling. Reaching the ceiling is not an account failure. |
| `status` | `in_progress`, `completed`, `incomplete`, or `skipped`. |
| `outcome` | `success` when completed and `accounts_failed` is 0. `failed` when completed and `accounts_failed` is greater than 0. Otherwise the same as `status`. |
| `actor_id` | Person who started the run. |
| `batch_failure_reason` | Why the run did not finish. Null when it finished or is still in progress. |
| `failures` | One object per failed account. Empty when none failed. |
| `alert` | The did-not-complete alert, or null. |
| `skipped_at` | When an operator skipped the run. Null unless `status` is `skipped`. |
| `skipped_by` | Person who skipped it. |
| `skip_reason` | Why it was skipped. |
| `superseded_by_run_id` | Later finished run of the same recognition date that resolved an incomplete run. Null otherwise. |

A completed run has a finish timestamp. Every other status has a null finish timestamp. A skipped run has skip time, skip actor, and skip reason. An incomplete run has a non-empty `batch_failure_reason`.

There is at most one in-progress run per organisation, and at most one completed run per organisation per recognition date.

## Account failure

Stored in `batch_account_failures`. Nested on the run as `failures`.

| Field | Meaning |
|-------|---------|
| `account_id` | Account identifier. |
| `step` | `accrue`, `capitalise`, or `default_check`. The first step that failed. |
| `reason` | Specific reason, prefixed with the step, for example `accrue: missing day-count election`. |
| `recorded_at` | Johannesburg time when the failure was recorded. |

One failure row per account per run. The reason is never empty. A generic "error" is not written by the batch. If a step fails without a reason, the stored reason is `{step}: failed without a reason`.

## Alert

Stored in `batch_alerts`. Nested on the run as `alert`, and listed in `open_alerts` while unresolved.

| Field | Meaning |
|-------|---------|
| `id` | Alert identifier. |
| `batch_run_id` | Run that did not complete. |
| `organisation_id` | Organisation. |
| `recognition_date` | Recognition date of that run. |
| `raised_at` | Johannesburg time when the alert was recorded. |
| `reason` | Why the run has not completed. |
| `resolution` | Null while open. `resolved` when a later run of that date finishes. `skipped` when an operator skips the run. |
| `resolved_at` | When it was resolved or skipped. |
| `resolved_by` | Person who finished the resolving run, or who skipped. |

One alert per run. An open alert has a null resolution. A resolved or skipped alert has both `resolved_at` and `resolved_by`.

## Audit log

Stored in `audit_log`. There is no separate audit query route. The status query is the operator route. The audit row is the required record of actor, timestamp, and outcome.

| Field | Meaning |
|-------|---------|
| `id` | Audit identifier. |
| `organisation_id` | Organisation. |
| `actor_id` | Person for this outcome. The starter for start, success, failure, and incomplete. The skipping person for skip. The person who attempted a refused start for `start_refused`. |
| `recorded_at` | Johannesburg time of the outcome. |
| `action` | `daily_calculation_batch`. |
| `outcome` | `started`, `success`, `failed`, `incomplete`, `skipped`, or `start_refused`. |
| `batch_run_id` | Run, when one exists. Null when a start is refused before a run is created. |
| `detail` | What happened, including each account id and reason when accounts failed. |

A request with no actor is refused and is not audited, because an audit row requires an actor.

## Last successful and last failed

For one organisation:

- Last status is the run with the latest sequence, whatever its outcome.
- Last successful run is the latest completed run with `accounts_failed` 0.
- Last failed run is the latest run that is incomplete, skipped, or completed with `accounts_failed` greater than 0.

An in-progress run is last status when it is the latest run. It is not yet the last failed run. The status payload still reports it as blocking.
