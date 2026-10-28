# Batch status query

Operators read the last daily-batch status for one organisation with:

```text
GET /organisations/{organisation_id}/batch-status
```

`organisation_id` is the organisation identifier, one path segment. The route does not accept a query string. A query string is refused with 400 and the reason `this route does not accept a query string`.

The response is JSON. An organisation with no runs returns 200 and null run fields. That is a real status, not a missing route.

## Response

```json
{
  "organisation_id": "org-1",
  "timezone": "Africa/Johannesburg",
  "recognition_boundary": "00:00",
  "later_recognition_date_blocked": false,
  "block_reason": null,
  "open_recognition_date": null,
  "last_status": null,
  "last_successful_run": null,
  "last_failed_run": null,
  "open_alerts": []
}
```

| Field | Meaning |
|-------|---------|
| `timezone` | Always `Africa/Johannesburg`. |
| `recognition_boundary` | Always `00:00`. |
| `later_recognition_date_blocked` | True when a later recognition date must not start. |
| `block_reason` | Specific reason, or null. |
| `open_recognition_date` | Recognition date that may still be retried. Null when nothing is incomplete, and null while a run is in progress (a retry is also blocked until that run is skipped). |
| `last_status` | Latest run, or null. Shape in [schema.md](schema.md). |
| `last_successful_run` | Latest finished run with no account failures, or null. |
| `last_failed_run` | Latest incomplete, skipped, or finished-with-failures run, or null. |
| `open_alerts` | Alerts that are not resolved or skipped. |

Run objects include `failures` and `alert`, so the query shows the account identifier and reason for each failure on those runs.

## Commands that change the status

These are not the query. They are how a run gets into the query.

Start:

```text
POST /organisations/{organisation_id}/batch-runs
```

```json
{
  "actor_id": "person-1",
  "recognition_date": "2026-10-28",
  "account_ids": ["acc-1", "acc-2"]
}
```

`recognition_date` may instead be the exact instant `2026-10-28T00:00:00.000000+02:00`. If the body contains `organisation_id`, it must match the path.

| HTTP status | Meaning |
|-------------|---------|
| 201 | The batch finished and no account failed. Body is the run. `outcome` is `success`. |
| 200 | The batch finished and at least one account failed. Body is the run. `outcome` is `failed`. Read `failures`. HTTP 200 means the batch finished, not that every account succeeded. |
| 400 | The request is invalid. Body is `{ "error": "<reason>" }`. |
| 409 | A run is in progress, an unresolved incomplete run blocks this date, or this recognition date already finished. Body includes `error` and the blocking `run` when one exists. |
| 500 | The batch did not complete. Body includes `error` and the incomplete `run`. |
| 503 | The start could not be recorded, or the calculation steps are not configured. No account is processed. |

Skip a run that has not finished:

```text
POST /organisations/{organisation_id}/batch-runs/{run_id}/skip
```

```json
{
  "actor_id": "person-2",
  "reason": "ledger restored after the runner was killed"
}
```

| HTTP status | Meaning |
|-------------|---------|
| 200 | The run is skipped. Body is the run. |
| 400 | Actor or reason is missing. |
| 404 | The run is not on this organisation. |
| 409 | The run already finished or was already skipped. |

A skipped run remains the last failed run until a later failure or a later failed finish is newer. It no longer blocks a later recognition date. The same recognition date may be started again after the skip, because it has not finished.

## Example

After a finished run with one account failure, `GET /organisations/org-1/batch-status` returns `later_recognition_date_blocked: false`, `last_successful_run: null`, and `last_failed_run.failures` containing:

```json
{
  "account_id": "acc-2",
  "step": "default_check",
  "reason": "default_check: outside limit, threshold unset",
  "recorded_at": "2026-10-28T00:15:02.000000+02:00"
}
```

After a run that does not finish, the same query returns `later_recognition_date_blocked: true`, `open_recognition_date` set to that recognition date, and one object in `open_alerts`.
