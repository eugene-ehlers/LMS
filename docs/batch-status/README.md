# Daily calculation batch status

The daily calculation batch accrues, capitalises, and runs the morning default check for one organisation and one recognition date. This document is the behaviour. The stored fields are in [schema.md](schema.md). The operator query is in [query.md](query.md).

The recognition date is 00:00 Africa/Johannesburg. A calendar date is accepted and stored at that instant. An aware timestamp is accepted only when it is exactly that instant. Any other clock time is refused.

## Order

1. Record the start, with the actor and the Johannesburg start time, before any account is processed. If the start cannot be recorded, stop. No account is processed and no success is assumed.
2. For each account, in the order supplied:
   1. Accrue.
   2. Capitalise due interest and service fees.
   3. Default check.
3. If a step fails for an account, record that account identifier, the step, and the reason. Do not run the later steps for that account. Continue with the next account.
4. When every supplied account has been attempted, record the finish time, the number processed, the number failed, and the failure list.

Processed means the attempt was recorded. Failed means that attempt failed. An account that was never attempted is in neither count.

An empty account list can finish with both counts at zero. This repository has no ledger account registry, so the caller supplies the identifiers. See open issue J12.

## Outcomes

| Outcome | When |
|---------|------|
| `started` | Start was recorded. |
| `success` | Finish was recorded and no account failed. |
| `failed` | Finish was recorded and at least one account failed. |
| `incomplete` | The run did not finish. |
| `skipped` | An operator explicitly skipped a run that had not finished. |
| `start_refused` | A start was refused before a new run was recorded. |

Each of these is written to the audit log with the actor, the Johannesburg timestamp, and the outcome.

## When the batch does not complete

A run that does not finish raises an alert. A later recognition date does not start while that run is unresolved.

Unresolved means the run is still in progress, or it is incomplete and no later run for the same recognition date has finished. An explicit skip resolves it. A later finished run of the same recognition date also resolves it. The earlier incomplete run stays in the history and records which run superseded it.

A run left in progress, including after a hard stop, blocks every new start for that organisation, including a retry of the same date. The alert row is written when a later start is refused or when an operator skips the run. No timeout is applied. See open issue J10.

The operator who skips must supply an actor id and a specific reason. The skip is audited under that actor. The run that started keeps the original actor.

## Account failures on a finished batch

This is not a locked rule. It is the reading used until open issue J5 is locked.

A batch that records a finish has completed, even when some accounts failed. Those failures stay on the batch record and in the audit outcome `failed`. They are visible as the last failed run. They do not raise the did-not-complete alert and they do not block the next recognition date.

A finished recognition date is not started again. See open issue J9.

## What this batch does not call

Servicing.accept_payment, collection-file generation, and statement generation are not steps in this batch. Orchestration section 1 still lists receipt allocation on the due-date flow. See open issue J3.

The morning default check is not Collections.observe. See open issue J4.

## Gaps

Raised in docs/OPEN_ISSUES.md. Not treated as locked rules:

| ID | Point |
|----|--------|
| J1 | `docs/LOCKED_DECISIONS.md` is a stub. The last complete text was followed and not edited. |
| J2 | Decision 1 does not name Africa/Johannesburg. This batch does, because the batch requirement does. |
| J3 | Same-day receipt allocation is not inside this batch. |
| J4 | The morning default check has no locked module name. |
| J5 | Account failures on a finished batch do not block the next day. |
| J6 | A retry calculates every account again. Idempotency is not locked. |
| J7 | The actor is a supplied person id. Enigma is not called. No batch role is locked. |
| J8 | A missed calendar day does not by itself block a later date. |
| J9 | A finished recognition date cannot be started again. |
| J10 | The alert is a stored row. No delivery channel or timeout is locked. |
| J11 | Status by account, and UI-action status, are not implemented. |
| J12 | Account identifiers are supplied by the caller. |
