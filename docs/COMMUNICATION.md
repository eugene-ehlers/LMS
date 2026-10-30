# LMS Communication and Status Feedback

Standing rules for what the system must tell operators and users.
No silent failures. Every significant action reports its outcome.

Last updated: 2026-10-28

## Standing instruction for all agents

Before implementing any batch job, UI action, or external call:
1. Read this document and docs/LOCKED_DECISIONS.md.
2. Ensure the action reports start, finish, success, or failure with a reason.
3. If a path can fail silently, raise it explicitly. Do not leave it silent.

## 1. Daily calculation batch

- The daily calculation batch (accrue, capitalise, default check) must record:
  - Start timestamp (Africa/Johannesburg).
  - Finish timestamp (Africa/Johannesburg).
  - Number of accounts processed.
  - Number of accounts that failed.
  - For each failure: account identifier and the reason.
- If the batch does not complete, an alert is raised. The batch does not continue to the next day until the failure is resolved or explicitly skipped.
- Operators can see the last successful run and the last failed run.

## 2. User-interface actions

- Every UI action that changes data (book, payment, election edit, campaign apply, write-off, statement issue, restructure) must return:
  - Success, with a confirmation the user can continue, or
  - Failure, with a reason the user can act on.
- The reason must be specific (for example "missing election: residual threshold" or "Enigma timeout"). A generic "error" is not sufficient.
- The UI does not proceed to the next step until the current action has reported success or the user has acknowledged the failure.

## 3. External calls

- Calls to Enigma, the decision-engine dummy (or real engine), the debit-order rail dummy (or real rail), and the push provider must report:
  - Success, or
  - Failure with the external reason (timeout, rejected, unavailable).
- A timeout or an ambiguous response fails closed and is reported. It is not treated as success.

## 4. Audit and operator visibility

- Every reported success or failure is written to the audit log with the actor, the timestamp, and the outcome.
- Operators can query the last status of any batch or UI action by account or by organisation.

## How to raise a gap

If a path can complete without reporting its outcome:
1. Do not leave it silent.
2. Record the gap in docs/OPEN_ISSUES.md.
3. Add the missing report before the path is used in production.
